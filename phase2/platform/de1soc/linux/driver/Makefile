# SPDX-License-Identifier: MIT
obj-m += trecap_platform.o
KERNEL_BUILD ?= /lib/modules/$(shell uname -r)/build
.PHONY: all clean
all:
	$(MAKE) -C "$(KERNEL_BUILD)" M="$(CURDIR)" modules
clean:
	$(MAKE) -C "$(KERNEL_BUILD)" M="$(CURDIR)" clean
