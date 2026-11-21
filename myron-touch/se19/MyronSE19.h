/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef MYRON_SE19_H
#define MYRON_SE19_H
#include "../MyronFT3683.h"
#ifdef __cplusplus
extern "C" {
#endif
#include "GeniSpi.h"

/* The platform owns clocks, pins and the live mapping for this engine. The
 * GENI instance and its buffers must outlive the sensor, including polling.
 * source_hz and selector describe the selected board clock, not the SPI rate. */
int myron_se19_start(struct myron_touch *sensor, struct geni_spi *engine,
                     unsigned source_hz, unsigned selector);
#ifdef __cplusplus
}
#endif
#endif
