// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#ifndef __cplusplus
#include <stdbool.h>
#else
extern "C" {
#endif
// Callback and ring storage live for the entire boot. Once registered, a
// failed query holds the frame; it must never mean "CPU-only" again.
typedef bool (*MyronGpuFenceQuery)(uint32_t *,uint32_t *,uint32_t *);
bool myron_display_register_gpu_fences(MyronGpuFenceQuery);
bool myron_gpu_query_fences(uint32_t *,uint32_t *,uint32_t *);
#ifdef __cplusplus
}
#endif
