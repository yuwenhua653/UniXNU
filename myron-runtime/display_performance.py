"""Use write-combined GOP pixel memory and retain bounded copy observations."""

def apply(board, replace):
    display=board/'display'
    p=display/'NativeLegacyDisplay.cpp'
    replace(p,'extern "C" void native_legacy_copy_timing_observed(uint64_t ticks,uint64_t bytes);',
        'extern "C" void native_legacy_copy_timing_observed(uint64_t ticks,uint64_t bytes);\n'
        'extern "C" void myron_display_mapping_observed(unsigned);\n'
        'extern "C" void myron_display_copy_path_observed(unsigned);')
    # Only the already validated GOP pixel range. MDP registers keep their
    # original device mapping; this does not enable cached write-back scanout.
    replace(p,'        IOMemoryMap *mapping=provider->mapDeviceMemoryWithIndex(0,kIOMapInhibitCache);',
        '''        unsigned scanoutMode=kIOMapWriteCombineCache;
        IOMemoryMap *mapping=provider->mapDeviceMemoryWithIndex(0,scanoutMode);
        if(!mapping) {
            scanoutMode=kIOMapInhibitCache;
            mapping=provider->mapDeviceMemoryWithIndex(0,scanoutMode);
        }
        myron_display_mapping_observed(mapping?scanoutMode:0);
'''.rstrip())
    replace(p,'            if(!native_legacy_fill_pixels(',
        '            myron_display_copy_path_observed(0);\n'
        '            uint64_t copyStart;__asm__ volatile("isb\\n\\tmrs %0, cntpct_el0":"=r"(copyStart));\n'
        '            if(!native_legacy_fill_pixels(')
    replace(p,'            shadowValid=false;\n            transferred=true;',
        '            {uint64_t copyEnd;__asm__ volatile("isb\\n\\tmrs %0, cntpct_el0":"=r"(copyEnd));native_legacy_copy_timing_observed(copyEnd-copyStart,blankLength);}\n'
        '            shadowValid=false;\n            transferred=true;')
    replace(p,'            myron_present_rect(',
        '            myron_display_copy_path_observed(1);\n'
        '            uint64_t copyStart;__asm__ volatile("isb\\n\\tmrs %0, cntpct_el0":"=r"(copyStart));\n'
        '            myron_present_rect(')
    replace(p,'            map->release();shadowValid=false;transferred=true;',
        '            {uint64_t copyEnd;__asm__ volatile("isb\\n\\tmrs %0, cntpct_el0":"=r"(copyEnd));native_legacy_copy_timing_observed(copyEnd-copyStart,length);}\n'
        '            map->release();shadowValid=false;transferred=true;')
    replace(p,'            if(!convertHalfRows(',
        '            myron_display_copy_path_observed(2);\n            if(!convertHalfRows(')
    replace(p,'        uint64_t stored=UINT64_MAX;',
        '        myron_display_copy_path_observed(3);\n        uint64_t stored=UINT64_MAX;')
    p=display/'MyronDisplayProbe.cpp'
    replace(p,'static uint32_t refreshHz,refreshNotifications,refreshIdlePolls;',
        '''static uint32_t refreshHz,refreshNotifications,refreshIdlePolls;
static uint32_t scanoutMapRequest,copySamples,copyPaths[4];
static uint64_t copyLastTicks,copyMaxTicks,copyTotalTicks,copyTotalBytes,copyCounterHz;''')
    replace(p,'    for(unsigned i=0;i<sizeof(firstOpens)',
        '''    if(used<cap-1) {
        n=snprintf(out+used,cap-used,
            "display_copy map_request=%u samples=%u ticks=%llu max_ticks=%llu total_ticks=%llu hz=%llu bytes=%llu paths=%u/%u/%u/%u\\n",
            scanoutMapRequest,copySamples,(unsigned long long)copyLastTicks,(unsigned long long)copyMaxTicks,
            (unsigned long long)copyTotalTicks,(unsigned long long)copyCounterHz,(unsigned long long)copyTotalBytes,
            copyPaths[0],copyPaths[1],copyPaths[2],copyPaths[3]);
        if(n>0)used+=(size_t)n<cap-used?(size_t)n:cap-used-1;
    }
    for(unsigned i=0;i<sizeof(firstOpens)''')
    replace(p,'extern "C" void native_legacy_copy_timing_observed(uint64_t,uint64_t) {}',
        '''extern "C" void myron_display_mapping_observed(unsigned mode) {scanoutMapRequest=mode;}
extern "C" void myron_display_copy_path_observed(unsigned path) {if(path<4)++copyPaths[path];}
extern "C" void native_legacy_copy_timing_observed(uint64_t ticks,uint64_t bytes) {
    uint64_t hz;__asm__ volatile("mrs %0, cntfrq_el0":"=r"(hz));
    copyCounterHz=hz;copyLastTicks=ticks;if(ticks>copyMaxTicks)copyMaxTicks=ticks;
    copyTotalTicks+=ticks;copyTotalBytes+=bytes;++copySamples;
}''')
