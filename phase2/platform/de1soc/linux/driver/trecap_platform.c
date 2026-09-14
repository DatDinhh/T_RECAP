// SPDX-License-Identifier: MIT
// Linux 6.12 baseline: one owner of reserved DDR mapping and codec bus grant.
#include <linux/atomic.h>
#include <linux/fs.h>
#include <linux/gpio/consumer.h>
#include <linux/io.h>
#include <linux/miscdevice.h>
#include <linux/mm.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include "../../../../sw/hps/include/trecap_ring_device.h"
#include "../../../../sw/hps/include/generated/trecap_csr.h"

struct trecap_platform {
    struct miscdevice misc;
    struct trecap_ring_device_info info;
    struct gpio_desc *codec_mux;
    void __iomem *csr;
    atomic_t opened;
};

static int trecap_open(struct inode *inode, struct file *file)
{
    struct miscdevice *misc = file->private_data;
    struct trecap_platform *ctx = container_of(misc, struct trecap_platform, misc);
    if (file->f_mode & FMODE_WRITE)
        return -EACCES;
    /* The FPGA ring contract has exactly one HPS consumer. */
    if (atomic_cmpxchg(&ctx->opened, 0, 1))
        return -EBUSY;
    file->private_data = ctx;
    return nonseekable_open(inode, file);
}

static int trecap_release(struct inode *inode, struct file *file)
{
    struct trecap_platform *ctx = file->private_data;
    atomic_set(&ctx->opened, 0);
    return 0;
}

static long trecap_ioctl(struct file *file, unsigned int command, unsigned long argument)
{
    struct trecap_platform *ctx = file->private_data;
    if (command != TRECAP_RING_GET_INFO)
        return -ENOTTY;
    return copy_to_user((void __user *)argument, &ctx->info, sizeof(ctx->info)) ? -EFAULT : 0;
}

static int trecap_mmap(struct file *file, struct vm_area_struct *vma)
{
    struct trecap_platform *ctx = file->private_data;
    unsigned long length = vma->vm_end - vma->vm_start;
    if (!(vma->vm_flags & VM_SHARED) || (vma->vm_flags & (VM_WRITE | VM_EXEC)) ||
        vma->vm_pgoff != 0 || length != ctx->info.size_bytes)
        return -EINVAL;
    /* no-map DT reservation prevents a conflicting cached linear mapping. */
    vm_flags_clear(vma, VM_MAYWRITE | VM_MAYEXEC);
    vm_flags_set(vma, VM_IO | VM_PFNMAP | VM_DONTEXPAND | VM_DONTDUMP);
    vma->vm_page_prot = pgprot_noncached(vma->vm_page_prot);
    return remap_pfn_range(vma, vma->vm_start,
                          (unsigned long)(ctx->info.physical_base >> PAGE_SHIFT),
                          length, vma->vm_page_prot);
}

static const struct file_operations trecap_fops = {
    .owner = THIS_MODULE,
    .open = trecap_open,
    .release = trecap_release,
    .unlocked_ioctl = trecap_ioctl,
    .compat_ioctl = trecap_ioctl,
    .mmap = trecap_mmap,
    .llseek = no_llseek,
};

static void trecap_release_codec(void *data)
{
    struct trecap_platform *ctx = data;
    /* Complete FPGA grant revocation before returning the physical mux to HPS. */
    writel(0, ctx->csr + TCSR_PLATFORM_CONTROL_OFFSET);
    readl(ctx->csr + TCSR_PLATFORM_CONTROL_OFFSET);
    gpiod_set_value_cansleep(ctx->codec_mux, 1);
}

static int trecap_probe(struct platform_device *pdev)
{
    struct device *dev = &pdev->dev;
    struct device_node *region;
    struct resource resource;
    struct resource *csr_resource;
    struct trecap_platform *ctx;
    int error;

    region = of_parse_phandle(dev->of_node, "memory-region", 0);
    if (!region)
        return dev_err_probe(dev, -EINVAL, "memory-region is required\n");
    if (!of_property_read_bool(region, "no-map") || of_property_read_bool(region, "reusable")) {
        of_node_put(region);
        return dev_err_probe(dev, -EINVAL, "ring must be reserved no-map, not reusable\n");
    }
    error = of_address_to_resource(region, 0, &resource);
    of_node_put(region);
    if (error)
        return dev_err_probe(dev, error, "invalid ring resource\n");
    if (resource.start != 0x3e000000ULL || resource_size(&resource) != 0x02000000ULL ||
        !PAGE_ALIGNED(resource.start) || !PAGE_ALIGNED(resource_size(&resource)))
        return dev_err_probe(dev, -EINVAL, "ring must match the DE1-SoC aperture\n");

    ctx = devm_kzalloc(dev, sizeof(*ctx), GFP_KERNEL);
    if (!ctx)
        return -ENOMEM;
    ctx->info.abi_version = TRECAP_RING_DEVICE_ABI;
    ctx->info.flags = TRECAP_RING_MAP_NONCACHED | TRECAP_RING_MAP_READ_ONLY;
    ctx->info.physical_base = resource.start;
    ctx->info.size_bytes = resource_size(&resource);
    atomic_set(&ctx->opened, 0);

    csr_resource = platform_get_resource(pdev, IORESOURCE_MEM, 0);
    if (!csr_resource || csr_resource->start != 0xff200000ULL ||
        resource_size(csr_resource) != 0x1000ULL)
        return dev_err_probe(dev, -EINVAL, "CSR resource must be 0xff200000/0x1000\n");
    ctx->csr = devm_ioremap_resource(dev, csr_resource);
    if (IS_ERR(ctx->csr))
        return PTR_ERR(ctx->csr);
    if (readl(ctx->csr + TCSR_ID_OFFSET) != TCSR_ID_VALUE ||
        readl(ctx->csr + TCSR_PLATFORM_CAPABILITY_OFFSET) != TCSR_PLATFORM_CAPABILITY_RESET)
        return dev_err_probe(dev, -ENODEV, "matching FPGA platform-grant ABI is required\n");
    writel(0, ctx->csr + TCSR_PLATFORM_CONTROL_OFFSET);
    if (readl(ctx->csr + TCSR_PLATFORM_CONTROL_OFFSET) != 0)
        return dev_err_probe(dev, -EIO, "cannot revoke FPGA codec grant\n");

    /* DT names portb offset19, which is HPS_GPIO48; no global gpiochip numbering. */
    ctx->codec_mux = devm_gpiod_get(dev, "codec-mux", GPIOD_OUT_LOW);
    if (IS_ERR(ctx->codec_mux))
        return dev_err_probe(dev, PTR_ERR(ctx->codec_mux), "codec bus grant unavailable\n");
    error = devm_add_action_or_reset(dev, trecap_release_codec, ctx);
    if (error)
        return error;
    error = gpiod_get_value_cansleep(ctx->codec_mux);
    if (error != 0)
        return dev_err_probe(dev, error < 0 ? error : -EIO, "GPIO48 output-low readback failed\n");
    writel(TCSR_PLATFORM_CONTROL_CODEC_FPGA_GRANT_MASK,
           ctx->csr + TCSR_PLATFORM_CONTROL_OFFSET);
    if (readl(ctx->csr + TCSR_PLATFORM_CONTROL_OFFSET) != TCSR_PLATFORM_CONTROL_CODEC_FPGA_GRANT_MASK)
        return dev_err_probe(dev, -EIO, "FPGA codec grant readback failed\n");

    ctx->misc.minor = MISC_DYNAMIC_MINOR;
    ctx->misc.name = "trecap-ring";
    ctx->misc.fops = &trecap_fops;
    ctx->misc.parent = dev;
    ctx->misc.mode = 0400;
    platform_set_drvdata(pdev, ctx);
    error = misc_register(&ctx->misc);
    if (error)
        return error;
    dev_info(dev, "reserved ring mapped read-only/noncached; FPGA codec grant held\n");
    return 0;
}

static void trecap_remove(struct platform_device *pdev)
{
    struct trecap_platform *ctx = platform_get_drvdata(pdev);
    misc_deregister(&ctx->misc);
}

static void trecap_shutdown(struct platform_device *pdev)
{
    struct trecap_platform *ctx = platform_get_drvdata(pdev);
    trecap_release_codec(ctx);
}

static const struct of_device_id trecap_of_match[] = {
    { .compatible = "trecap,de1soc-platform-v1" },
    { }
};
MODULE_DEVICE_TABLE(of, trecap_of_match);
static struct platform_driver trecap_driver = {
    .probe = trecap_probe,
    .remove = trecap_remove,
    .shutdown = trecap_shutdown,
    .driver = {
        .name = "trecap-platform",
        .of_match_table = trecap_of_match,
        .suppress_bind_attrs = true,
    },
};
module_platform_driver(trecap_driver);
MODULE_DESCRIPTION("T-RECAP DE1-SoC reserved ring and codec grant owner");
MODULE_AUTHOR("T-RECAP project team");
MODULE_LICENSE("Dual MIT/GPL");
