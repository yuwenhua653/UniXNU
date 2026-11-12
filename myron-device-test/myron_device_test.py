#!/usr/bin/env python3
"""Windows/Linux companion for the exact successful myron device package.

No Android root, repartitioning, slot switch, AVB changes or bootloader unlock.
Recovery must already provide root ADB. Only an explicit install/start/restore
command can write a partition. This program has not been tested on a handset.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import zipfile
import device_layout as layout

RUN = 43165530177
ARCHIVE_SHA = '5147cdae6353d979ff5dcb3472cd9a71cbce3399aaf0119dc4e87b2ea87d34b0'
ROOT_SHA = '7d3b1200d14e4f27f12ef1680184033b0f95035475635f57c5b4130c28cdb81c'
ROOT_BYTES = 15092154368
FILES = ('root-container.raw','policy-carrier.bin','root.img','root-startup.img')
BLOCK = 4096
CHUNK = 64 * 1024**2
REMOTE = '/tmp/myron-ios27-transfer.bin'
require = layout.require


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def regular(path):
    p=Path(path)
    require(p.is_file() and not p.is_symlink(),'Missing or non-regular file: '+str(p))
    return p


def save(path, obj):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.new')
    with tmp.open('w',encoding='utf-8') as f:
        json.dump(obj,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def load(path):
    p=regular(path);require(p.stat().st_size<=2*1024**2,'Oversized metadata')
    return json.loads(p.read_text(encoding='utf-8'))


def tool(name):
    here=Path(__file__).resolve().parent
    for p in (here/(name+'.exe'),here/'platform-tools'/(name+'.exe')):
        if p.is_file():return str(p)
    found=shutil.which(name)
    require(found is not None,'Install Android platform-tools or put '+name+' in PATH')
    return found


def invoke(command, timeout=120):
    r=subprocess.run(list(map(str,command)),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    require(r.returncode==0,'Command failed: '+str(command[0])+' '+r.stderr.decode(errors='replace')[-1500:])
    return r.stdout


def unpack(archive, package):
    archive=regular(archive);package=Path(package)
    require(not package.exists(),'Package directory already exists; use verify instead')
    print('Checking the 10.36 GB archive SHA256...',flush=True)
    require(sha(archive)==ARCHIVE_SHA,'Not the approved successful build archive')
    with zipfile.ZipFile(archive) as z:
        entries=z.infolist()
        expected=set(FILES)|{'deployment.json'}
        require(len(entries)==5 and {i.filename for i in entries}==expected,'Unexpected archive paths')
        require(all(not stat.S_ISLNK(i.external_attr>>16) and not i.flag_bits&1 for i in entries),'Unsupported archive entry')
        size=sum(i.file_size for i in entries)
        require(ROOT_BYTES<size<ROOT_BYTES+1024**3,'Unexpected package size')
        package.parent.mkdir(parents=True,exist_ok=True)
        require(shutil.disk_usage(package.parent).free>size+512*1024**2,'Need at least 16 GB free to extract')
        with tempfile.TemporaryDirectory(prefix='myron-extract-',dir=package.parent) as tmp:
            work=Path(tmp)/'package';work.mkdir()
            for i in entries:
                with z.open(i) as src,(work/i.filename).open('xb') as dst:
                    shutil.copyfileobj(src,dst,8*1024**2)
            save(work/'archive-proof.json',dict(run=RUN,archive_sha256=ARCHIVE_SHA,manifest_sha256=sha(work/'deployment.json')))
            verify(work)
            work.rename(package)
    print('Package extracted and verified.')


def verify(package):
    package=Path(package)
    proof=load(package/'archive-proof.json')
    require(proof.get('run')==RUN and proof.get('archive_sha256')==ARCHIVE_SHA and
            proof.get('manifest_sha256')==sha(regular(package/'deployment.json')),'Run unpack on the original Actions ZIP first')
    m=load(package/'deployment.json')
    require(m.get('format')==1 and m.get('device')=='myron' and m.get('partition')=='unixnu' and
            m.get('device_bound') is True and m.get('qualification_only') is False,'Wrong device deployment package')
    require(m.get('device_writes')==0 and m.get('requires_live_gpt_check') is True and
            m.get('requires_fresh_android_boot_backup') is True,'Missing deployment prerequisites')
    require(set(m['files'])==set(FILES),'Wrong package filenames')
    for name,row in m['files'].items():
        p=regular(package/name)
        require(type(row['bytes']) is int and 0<row['bytes']<=ROOT_BYTES,'Invalid file size')
        print('Verifying '+name,flush=True)
        require(p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],'Changed package file: '+name)
    require(m['files']['root-container.raw']==dict(bytes=ROOT_BYTES,sha256=ROOT_SHA),'Wrong original root image')
    require(m['layout']['partition_bytes']==32*1024**3,'Unexpected unixnu size')
    geo=layout.allocate(m['layout'],ROOT_BYTES,m['files']['policy-carrier.bin']['bytes'])
    require(geo==m['geometry'],'Changed root geometry')
    expected=[dict(file='root-container.raw',partition_offset=0,bytes=ROOT_BYTES),
              dict(file='policy-carrier.bin',partition_offset=geo['carrierOffset'],bytes=geo['carrierCapacity'])]
    require(m['root_writes']==expected,'Changed write ranges')
    for name in ('root.img','root-startup.img'):
        with (package/name).open('rb') as f:header=f.read(4096)
        require(header[:8]==b'ANDROID!' and struct.unpack_from('<I',header,40)[0]==4,'Expected Android boot v4')
    return m


class Recovery:
    def __init__(self, adb):
        self.adb=adb
        rows=[r.split() for r in invoke([adb,'devices']).decode().splitlines()[1:] if r.strip()]
        require(len(rows)==1 and rows[0][1] in ('device','recovery'),'Connect exactly one authorized recovery device')
        self.serial=rows[0][0]
        require(re.fullmatch(r'[A-Za-z0-9_-]+',self.serial) is not None,'Require a USB device serial')
        require(self.shell('getprop','ro.product.device')=='myron','Device is not myron')
        require(self.shell('id','-u')=='0','Recovery needs root ADB; Android does not need root')
        require(self.shell('getprop','ro.bootmode')=='recovery' or self.shell('getprop','init.svc.recovery')=='running','Enter recovery main screen, not Android/sideload')
        self.slot=self.shell('getprop','ro.boot.slot_suffix').lstrip('_')
        require(self.slot in ('a','b'),'Unknown recovery boot slot')

    def call(self,*args,timeout=120):return invoke([self.adb,'-s',self.serial,*args],timeout)
    def shell(self,*args):return self.call('shell',*args).decode().strip()

    def capture(self, directory):
        layout.capture(self.adb,directory,self.serial)
        disk,binding=layout.read_capture(directory)
        target='/dev/block/sda'+str(disk['partition_index'])
        require(self.shell('readlink','-f','/dev/block/by-name/unixnu')==target,'unixnu mapping changed')
        require(self.shell('cat','/sys/class/block/'+Path(target).name+'/start')==str(disk['first']*8),'Kernel start differs from GPT')
        require(self.shell('cat','/sys/class/block/'+Path(target).name+'/size')==str(disk['partition_bytes']//512),'Kernel size differs from GPT')
        devno=self.shell('cat','/sys/class/block/'+Path(target).name+'/dev')
        mounts=self.shell('cat','/proc/self/mountinfo')
        require(re.fullmatch(r'[0-9]+:[0-9]+',devno) is not None,'Invalid unixnu device number')
        require(not any(len(line.split())>2 and line.split()[2]==devno for line in mounts.splitlines()),'unixnu is mounted')
        return disk,binding,target

    def boot(self):
        name='boot_'+self.slot
        path=self.shell('readlink','-f','/dev/block/by-name/'+name)
        require(re.fullmatch(r'/dev/block/sd[a-z][1-9][0-9]*',path) is not None,'Unexpected boot mapping')
        size=int(self.shell('blockdev','--getsize64',path))
        require(16*1024**2<=size<=256*1024**2 and size%BLOCK==0,'Unexpected boot capacity')
        return name,path,size

    def read(self,path,offset,size):
        require(re.fullmatch(r'/dev/block/sd[a-z][1-9][0-9]*',path) is not None,'Invalid block read path')
        require(offset>=0 and offset%BLOCK==0 and 0<size<=CHUNK and size%BLOCK==0,'Invalid block read range')
        data=self.call('exec-out','dd','if='+path,'bs=4096','skip='+str(offset//BLOCK),'count='+str(size//BLOCK),timeout=300)
        require(len(data)==size,'Short/contaminated device read')
        return data

    def write(self,target,offset,data,host_chunk):
        require(re.fullmatch(r'/dev/block/sda[1-9][0-9]*',target) is not None,'Only unixnu LUN0 writes allowed')
        require(self.shell('readlink','-f','/dev/block/by-name/unixnu')==target,'unixnu mapping changed')
        require(offset>=0 and offset%BLOCK==0 and 0<len(data)<=CHUNK and len(data)%BLOCK==0,'Invalid block write range')
        host_chunk.write_bytes(data)
        self.call('push',str(host_chunk),REMOTE,timeout=300)
        require(self.shell('sha256sum',REMOTE).split()[0]==hashlib.sha256(data).hexdigest(),'Transfer hash differs')
        self.shell('dd','if='+REMOTE,'of='+target,'bs=4096','seek='+str(offset//BLOCK),'count='+str(len(data)//BLOCK),'conv=notrunc')
        self.shell('sync')


def read_hash(device,path,size,output=None):
    h=hashlib.sha256()
    for off in range(0,size,CHUNK):
        raw=device.read(path,off,min(CHUNK,size-off));h.update(raw)
        if output:output.write(raw)
    return h.hexdigest()


def backup_state(state):
    state=Path(state);b=load(state/'backup.json')
    require(b.get('format')==1 and b.get('device')=='myron' and b.get('slot') in ('a','b'),'Invalid backup metadata')
    require(b.get('android_confirmed') is True and b.get('boot_name')=='boot_'+b['slot'],'Not a confirmed Android boot backup')
    require(b.get('run')==RUN and b.get('archive_sha256')==ARCHIVE_SHA,'Backup belongs to a different test package')
    require(re.fullmatch('[A-Za-z0-9_-]+',b.get('serial','')) is not None,'Invalid backup device serial')
    boot=regular(state/(b['boot_name']+'.img'))
    require(type(b['boot_bytes']) is int and 16*1024**2<=b['boot_bytes']<=256*1024**2 and
            boot.stat().st_size==b['boot_bytes'] and sha(boot)==b['boot_sha256'],'Boot backup changed')
    return b


def match_layout(disk, expected, capture, parent):
    if disk==expected:return
    results=Path(parent)/'results';results.mkdir(exist_ok=True)
    saved=Path(tempfile.mkdtemp(prefix='gpt-mismatch-',dir=results))
    shutil.copytree(capture,saved,dirs_exist_ok=True)
    raise ValueError('Current GPT differs from successful build; capture saved: '+str(saved))


def live(device, m, parent):
    with tempfile.TemporaryDirectory(prefix='gpt-',dir=parent) as tmp:
        capture=Path(tmp)/'capture'
        disk,binding,target=device.capture(capture)
        match_layout(disk,m['layout'],capture,parent)
    return binding,target


def prepare(package,state,device):
    m=verify(package);state=Path(state)
    require(not state.exists(),'Keep existing state/backup; do not replace it')
    state.parent.mkdir(parents=True,exist_ok=True)
    require(shutil.disk_usage(state.parent).free>1024**3,'Need 1 GB free for backup')
    with tempfile.TemporaryDirectory(prefix='myron-backup-',dir=state.parent) as tmp:
        work=Path(tmp);disk,binding,target=device.capture(work/'capture')
        match_layout(disk,m['layout'],work/'capture',state.parent)
        name,path,size=device.boot()
        print('Backing up '+name+' and reading it twice...',flush=True)
        with (work/(name+'.img')).open('xb') as f:
            digest=read_hash(device,path,size,f);f.flush();os.fsync(f.fileno())
        require(digest==read_hash(device,path,size),'Boot changed during backup')
        with (work/(name+'.img')).open('rb') as f:require(f.read(8)==b'ANDROID!','Backup is not an Android boot image')
        final_binding,_=live(device,m,work)
        require(final_binding==binding,'GPT changed during backup')
        save(work/'backup.json',dict(format=1,device='myron',serial=device.serial,slot=device.slot,boot_name=name,
            boot_bytes=size,boot_sha256=digest,boot_path=path,layout=disk,capture_binding=binding,
            run=RUN,archive_sha256=ARCHIVE_SHA,manifest_sha256=sha(Path(package)/'deployment.json'),android_confirmed=True))
        work.rename(state)
    print('Current GPT matched; Android boot backup saved. Device writes: 0.')


def install(package,state,device):
    package=Path(package);state=Path(state);m=verify(package);b=backup_state(state)
    require((device.serial,device.slot)==(b['serial'],b['slot']),'Device/slot differs from backup')
    require(sha(package/'deployment.json')==b['manifest_sha256'],'Package differs from backup session')
    binding,target=live(device,m,state)
    require(binding==b['capture_binding'],'GPT changed since backup')
    name,boot,size=device.boot()
    require((name,size)==(b['boot_name'],b['boot_bytes']) and read_hash(device,boot,size)==b['boot_sha256'],'Android boot differs from fresh backup')
    receipt=dict(format=1,run=RUN,serial=device.serial,slot=device.slot,manifest_sha256=b['manifest_sha256'],
                 capture_binding=binding,complete=False,chunks=[])
    save(state/'root-install.json',receipt)
    with tempfile.TemporaryDirectory(prefix='chunks-',dir=state) as tmp:
        chunkfile=Path(tmp)/'chunk.bin'
        for row in m['root_writes']:
            with regular(package/row['file']).open('rb') as src:
                for offset in range(0,row['bytes'],CHUNK):
                    n=min(CHUNK,row['bytes']-offset);raw=src.read(n);absolute=row['partition_offset']+offset
                    require(len(raw)==n and absolute+n<=m['layout']['partition_bytes'],'Truncated/out-of-range root write')
                    expected=hashlib.sha256(raw).hexdigest()
                    # Recheck GPT for every chunk; reconnects never select a new serial.
                    now,path=live(device,m,state)
                    require(now==binding and path==target,'Live partition changed')
                    existing=device.read(target,absolute,n)
                    if hashlib.sha256(existing).hexdigest()!=expected:
                        device.write(target,absolute,raw,chunkfile)
                        require(hashlib.sha256(device.read(target,absolute,n)).hexdigest()==expected,'Readback mismatch; Android boot was not modified')
                    receipt['chunks'].append(dict(file=row['file'],offset=offset,bytes=n,sha256=expected))
                    save(state/'root-install.json',receipt)
                    print(f"{row['file']}: {offset+n}/{row['bytes']} verified",flush=True)
    require(live(device,m,state)[0]==binding,'GPT changed after installation')
    require(read_hash(device,boot,size)==b['boot_sha256'],'Android boot changed during root installation')
    receipt['complete']=True;save(state/'root-install.json',receipt)
    device.shell('rm','-f',REMOTE)
    print('unixnu installed and read back. Android boot unchanged. Enter bootloader fastboot manually for start.')


class Fastboot:
    def __init__(self, executable, backup):
        self.exe=executable;self.serial=backup['serial']
        rows=[r.split() for r in invoke([executable,'devices']).decode().splitlines() if r.strip()]
        require(len(rows)==1 and rows[0][0]==self.serial,'Connect the same single device in bootloader fastboot')
        require(self.get('product')=='myron','Fastboot product differs')
        require(self.get('is-userspace')=='no','Use bootloader fastboot, not fastbootd')
        require(self.get('unlocked') in ('yes','true'),'Bootloader must already be unlocked')
        require(self.get('current-slot')==backup['slot'],'Fastboot slot changed; do not switch slots')
        require(int(self.get('partition-size:'+backup['boot_name']),16)==backup['boot_bytes'],'Boot partition size differs')

    def get(self,name):
        r=subprocess.run([self.exe,'-s',self.serial,'getvar',name],capture_output=True,timeout=30)
        require(r.returncode==0,'Unsupported fastboot variable: '+name)
        text=(r.stdout+r.stderr).decode(errors='replace')
        values=re.findall(r'^(?:\(bootloader\)\s*)?'+re.escape(name)+r':\s*(\S+)\s*$',text,re.M)
        require(len(values)==1,'Cannot parse fastboot variable: '+name)
        return values[0]

    def flash(self,name,path):
        require(name in ('boot_a','boot_b'),'Only a named boot slot may be flashed')
        invoke([self.exe,'-s',self.serial,'flash',name,str(path)],300)

    def reboot(self):invoke([self.exe,'-s',self.serial,'reboot'])


def start(package,state,fastboot_factory):
    package=Path(package);state=Path(state);m=verify(package);b=backup_state(state)
    r=load(state/'root-install.json')
    require(r.get('complete') is True and r.get('run')==RUN and
            (r.get('serial'),r.get('slot'),r.get('manifest_sha256'),r.get('capture_binding'))==
            (b['serial'],b['slot'],b['manifest_sha256'],b['capture_binding']),'Root installation is incomplete or belongs to another session')
    require(sha(package/'deployment.json')==b['manifest_sha256'],'Package changed since installation')
    require(m['files']['root-startup.img']['bytes']<=b['boot_bytes'],'Startup image exceeds boot partition')
    fb=fastboot_factory(b)
    save(state/'boot-attempt.json',dict(run=RUN,slot=b['slot'],boot_sha256=m['files']['root-startup.img']['sha256'],flash_started=True,flash_completed=False))
    fb.flash(b['boot_name'],package/'root-startup.img')
    save(state/'boot-attempt.json',dict(run=RUN,slot=b['slot'],flash_started=True,flash_completed=True))
    fb.reboot()
    print('Startup probe installed; record the screen. If stuck, return to bootloader fastboot and run restore.')


def restore(state,fastboot_factory):
    state=Path(state);b=backup_state(state);fb=fastboot_factory(b)
    fb.flash(b['boot_name'],state/(b['boot_name']+'.img'))
    fb.reboot()
    print('Saved Android boot restored. unixnu contents remain the test root; Android data/GPT were not changed by this tool.')


def confirm(phrase):
    require(input('Type '+phrase+' to continue: ').strip()==phrase,'Cancelled before device writes')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('unpack','verify','prepare','install','start','restore'))
    p.add_argument('--archive',type=Path,default=Path('myron-ios27-device-root-package.zip'))
    p.add_argument('--package',type=Path,default=Path('package'));p.add_argument('--state',type=Path,default=Path('state'))
    a=p.parse_args()
    if a.action=='unpack':unpack(a.archive,a.package)
    elif a.action=='verify':verify(a.package);print('Package verified.')
    elif a.action=='prepare':
        print('Confirm this phone last booted working Android and is now in Recovery. Existing iOS boot is not an Android backup.')
        confirm('ANDROID');prepare(a.package,a.state,Recovery(tool('adb')))
    elif a.action=='install':
        print('This replaces the existing iOS contents of unixnu. Android boot remains unchanged.')
        confirm('INSTALL UNIXNU');install(a.package,a.state,Recovery(tool('adb')))
    elif a.action=='start':
        print('This flashes the startup probe to the backed-up current boot slot and reboots.')
        confirm('START IOS');start(a.package,a.state,lambda b:Fastboot(tool('fastboot'),b))
    else:
        confirm('RESTORE ANDROID');restore(a.state,lambda b:Fastboot(tool('fastboot'),b))


if __name__=='__main__':
    try:main()
    except (Exception,KeyboardInterrupt) as e:
        import datetime,traceback
        logs=Path('results');logs.mkdir(exist_ok=True)
        report=logs/('error-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.txt')
        report.write_text(traceback.format_exc(),encoding='utf-8')
        print('STOP:',str(e) or 'Interrupted')
        print('Error log:',report)
        print('Keep state and the Android backup. No automatic retry, repartition, or slot switch was performed.')
        raise SystemExit(1)
