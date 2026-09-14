/* SPDX-License-Identifier: MIT
 * Userspace ABI for the noncached, read-only telemetry ring mapping.
 * This local device ABI is independent of the FPGA CSR and UDP ABIs.
 */
#ifndef TRECAP_RING_DEVICE_H
#define TRECAP_RING_DEVICE_H
#include <linux/ioctl.h>
#include <linux/types.h>
#define TRECAP_RING_DEVICE_PATH "/dev/trecap-ring"
#define TRECAP_RING_DEVICE_ABI 1U
#define TRECAP_RING_MAP_NONCACHED 1U
#define TRECAP_RING_MAP_READ_ONLY 2U
struct trecap_ring_device_info {
    __u32 abi_version;
    __u32 flags;
    __u64 physical_base;
    __u64 size_bytes;
    __u64 reserved;
};
#define TRECAP_RING_GET_INFO _IOR('T', 0x01, struct trecap_ring_device_info)
#endif
