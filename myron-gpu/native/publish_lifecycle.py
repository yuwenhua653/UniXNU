"""Board-local fixes to the pinned IOKit frontend; the wire ABI is unchanged."""


def patch(text, replace):
    text = replace(text, '#include <kern/thread.h>',
                   '#include <kern/thread.h>\n#include <kern/task.h>')
    text = replace(text, '    bool live_=false;', '''    bool live_=false;
    // Under g.lock. Descriptor teardown must run outside that lock, but no
    // call may recycle its BO/token or acquire another view in that interval.
    bool view_teardown_=false;
    IOReturn view_error_=kIOReturnSuccess;
    task_t mailbox_task_=nullptr;
    void lockCore() {
        IOLockLock(g.lock);
        while(view_teardown_)IOLockSleep(g.lock,&view_teardown_,THREAD_UNINT);
    }
    void finishViewTeardown() {
        IOLockLock(g.lock);view_teardown_=false;
        IOLockWakeup(g.lock,&view_teardown_,false);IOLockUnlock(g.lock);
    }''')
    text = replace(text,
        '    IOReturn run(uint32_t method,const void *input,size_t input_size,void *output,size_t output_size);',
        '    IOReturn run(uint32_t method,const void *input,size_t input_size,void *output,size_t output_size,task_t importTask=nullptr);')
    text = replace(text, '    void setHandoffOnly()', '''    void setMailboxTask(task_t task) {task_reference(task);mailbox_task_=task;}
    void setHandoffOnly()''')
    text = replace(text, 'valid?runCore(owner,method,input,in_size,output,out_size):kIOReturnBadArgument',
                   'valid?owner->run(method,input,in_size,output,out_size,owner->mailbox_task_):kIOReturnBadArgument')
    text = replace(text,
        '        while(removeMappingForDescriptor(view))native_adreno_metal_diag.forced_unmaps=native_adreno_metal_diag.forced_unmaps+1;',
        '''        while(IOMemoryMap *mapping=removeMappingForDescriptor(view)) {
            // removeMappingForDescriptor returns a retained map. Explicitly
            // revoke it even when another reference still holds the object.
            const IOReturn status=mapping->unmap();
            mapping->release();
            if(status) {
                IOLockLock(g.lock);
                if(!view_error_)view_error_=status;
                IOLockUnlock(g.lock);
            } else native_adreno_metal_diag.forced_unmaps=native_adreno_metal_diag.forced_unmaps+1;
        }''')
    text = replace(text, '    dropViews(0);\n    IOLockLock(g.lock);', '''    lockCore();
    view_teardown_=true;
    IOLockUnlock(g.lock);
    dropViews(0);
    IOLockLock(g.lock);''')
    text = replace(text, '''    IOReturn status=kIOReturnSuccess;
    AGXDeviceUserClient *mailbox=nullptr;''', '''    IOReturn status=view_error_;
    AGXDeviceUserClient *mailbox=nullptr;''')
    text = replace(text, '''    if(live_) {
        const uint64_t peak''', '''    if(live_ && !status) {
        const uint64_t peak''')
    text = replace(text, '    if(mailbox)mailbox->release();', '''    finishViewTeardown();
    if(mailbox)mailbox->release();''')
    text = replace(text, '    IOUserClient::free();', '''    if(mailbox_task_) {task_deallocate(mailbox_task_);mailbox_task_=nullptr;}
    IOUserClient::free();''')
    text = replace(text, '    IOLockLock(g.lock);\n    if(!views_)views_=IONewZero(View,MaxViews);', '''    lockCore();
    if(!live_ || view_error_) {
        const IOReturn status=view_error_?view_error_:kIOReturnNotReady;
        IOLockUnlock(g.lock);return status;
    }
    if(!views_)views_=IONewZero(View,MaxViews);''')
    # Both the immediate and polling dispatch must respect the teardown gap.
    old = 'IOLockLock(g.lock);\n            status=connection->live_?connection->core_->dispatch'
    text = replace(text, old, 'connection->lockCore();\n            status=connection->live_?connection->core_->dispatch')
    text = replace(text, 'IOLockLock(g.lock);\n        status=connection->live_?connection->core_->dispatch',
                   'connection->lockCore();\n        status=connection->live_?connection->core_->dispatch')
    text = text.replace('status=connection->live_?connection->core_->dispatch',
                        'status=connection->view_error_?connection->view_error_:connection->live_?connection->core_->dispatch')
    text = replace(text, 'method==NativeAdrenoMethodWaitFence && connection->live_ && input',
                   'method==NativeAdrenoMethodWaitFence && input')
    text = replace(text,
        'IOReturn AGXDeviceUserClient::run(uint32_t method,const void *input,size_t input_size,void *output,size_t output_size)',
        'IOReturn AGXDeviceUserClient::run(uint32_t method,const void *input,size_t input_size,void *output,size_t output_size,task_t importTask)')
    start = text.index('    if(method==NativeAdrenoMethodBoCpuUnmap && input')
    end = text.index('    if(method==NativeAdrenoMethodBoImport)', start)
    text = text[:start] + '''    if(method==NativeAdrenoMethodBoCpuUnmap) {
        if(!input || input_size!=sizeof(NativeAdrenoAbiBoCpuUnmap) || output_size)
            return kIOReturnBadArgument;
        NativeAdrenoAbiBoCpuUnmap request{};
        memcpy(&request,input,sizeof(request));
        lockCore();
        // Validate handle, token, reserved fields and lease before side effects.
        const IOReturn status=view_error_?view_error_:live_?
            core_->cpuUnmap(&request):kIOReturnNotReady;
        const bool drain=!status && !core_->mappingLeases(request.token);
        if(drain)view_teardown_=true;
        else if(!status)native_adreno_view_kept=native_adreno_view_kept+1;
        IOLockUnlock(g.lock);
        if(drain) {
            dropViews(request.token);
            finishViewTeardown();
        }
        IOLockLock(g.lock);
        const IOReturn result=view_error_?view_error_:status;
        IOLockUnlock(g.lock);
        return result;
    }
''' + text[end:]
    text = replace(text, 'IOLockLock(g.lock);\n        const IOReturn status=live_?core_->importBo(&request,current_task(),&reply)',
                   'lockCore();\n        const IOReturn status=view_error_?view_error_:live_?core_->importBo(&request,importTask?importTask:current_task(),&reply)')
    # Only an admitted connection owns the task used by the kernel mailbox
    # worker. Direct calls continue to import the calling task's address range.
    text = replace(text, '    unsigned attach_state=0;',
                   '    connection->setMailboxTask(owningTask);\n    unsigned attach_state=0;')
    text = replace(text, '    native_adreno_metal_diag.attach_status=attach_state;', '''    native_adreno_metal_diag.attach_status=attach_state;
    if(attach_state!=1) {connection->release();return kIOReturnNotAttached;}
    auto discard=[&]() {connection->stop(provider);connection->detach(provider);connection->release();};''')
    text = replace(text, '''    if(type!=NativeAdrenoPluginOpenType) {
        connection->release();''', '''    if(type!=NativeAdrenoPluginOpenType) {
        discard();''')
    text = replace(text, '''    if(refusal) {
        connection->release();''', '''    if(refusal) {
        discard();''')
    return text
