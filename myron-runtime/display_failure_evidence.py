"""Identify first-frame rejection sites without acknowledging failed transfers."""

def apply(board, replace):
    display=board/'display'
    file=display/'NativeLegacyDisplay.cpp'
    replace(file,'extern "C" void myron_display_mapping_observed(unsigned);',
        'extern "C" void myron_display_mapping_observed(unsigned);\n'
        'extern "C" void myron_display_not_ready(unsigned);')
    # Guard the complete ordered contexts: changes to the donor must be reviewed.
    contexts=[
        '!native_legacy_surface_bounds(bw,bh,blank.v_rowBytes,bootMapping->getLength(),bootMapping->getLength())) {\n                ',
        'if(!native_legacy_prepare_scanout()) {',
        '!native_legacy_surface_bounds(width,height,video.v_rowBytes,bootMapping->getLength(),bootMapping->getLength())) {\n            ',
        'if(!native_legacy_prepare_scanout()) {',
        'OSSafeReleaseNULL(map);',
        'if(!native_legacy_prepare_scanout()) {OSSafeReleaseNULL(source);',
        'if(!native_legacy_prepare_scanout()) {\n            OSSafeReleaseNULL(source);',
    ]
    token='native_legacy_transfer_observed(kIOReturnNotReady,request,0);return;'
    text=file.read_text();parts=text.split(token)
    if len(parts)!=8 or any(not part.endswith(context) for part,context in zip(parts,contexts)):
        raise ValueError('Display NotReady sites changed; review seven guarded paths')
    file.write_text(''.join(part+f'myron_display_not_ready({i+1});'+token for i,part in enumerate(parts[:-1]))+parts[-1])
    file=display/'MyronDisplayProbe.cpp'
    replace(file,'static uint32_t scanoutMapRequest,copySamples,copyPaths[4];',
        'static uint32_t scanoutMapRequest,copySamples,copyPaths[4];\n'
        'static uint32_t transferNotReady[7],handoffObservation;')
    replace(file,'    for(unsigned i=0;i<sizeof(firstOpens)',
        '''    if(used<cap-1) {
        n=snprintf(out+used,cap-used,"display_not_ready sites=%u/%u/%u/%u/%u/%u/%u handoff=%u\\n",
            transferNotReady[0],transferNotReady[1],transferNotReady[2],transferNotReady[3],
            transferNotReady[4],transferNotReady[5],transferNotReady[6],handoffObservation);
        if(n>0)used+=(size_t)n<cap-used?(size_t)n:cap-used-1;
    }
    for(unsigned i=0;i<sizeof(firstOpens)''')
    replace(file,'extern "C" void myron_display_mapping_observed(unsigned mode) {scanoutMapRequest=mode;}',
        'extern "C" void myron_display_mapping_observed(unsigned mode) {scanoutMapRequest=mode;}\n'
        'extern "C" void myron_display_not_ready(unsigned site) {if(site && site<=7)++transferNotReady[site-1];}')
    replace(file,'    if(ml_at_interrupt_context() || !ml_get_interrupts_enabled())return false;',
        '    if(ml_at_interrupt_context()){handoffObservation=1;return false;}\n'
        '    if(!ml_get_interrupts_enabled()){handoffObservation=2;return false;}')
    replace(file,'        if(myron_boot_progress_prepare_scanout())return true;',
        '        if(myron_boot_progress_prepare_scanout()){handoffObservation=4;return true;}')
    replace(file,'    myron_boot_progress_cancel_scanout();return false;',
        '    handoffObservation=3;myron_boot_progress_cancel_scanout();return false;')
