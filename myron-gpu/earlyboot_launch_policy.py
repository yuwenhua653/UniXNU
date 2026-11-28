"""Check the retained 24A446 policy, not just a helper's valid code signature.

Read-only inspection: this never patches AMFI or changes global enforcement.
The reviewed category 5 requires trusted code and its original parent rule.
The actual system-service category mask accepts 5 and rejects the old zero.
"""
import hashlib,json,struct
from pathlib import Path


def require(ok,reason):
    if not ok:raise ValueError(reason)


def regions(raw):
    require(len(raw)>=32,'Short launch-policy kernel')
    magic,cpu,_,kind,count,size=struct.unpack_from('<6I',raw)
    require(magic==0xfeedfacf and cpu==0x100000c and kind==12 and
            0<count<=4096 and 32+size<=len(raw),'Invalid launch-policy fileset')
    at=32;result=[]
    for _ in range(count):
        require(at+8<=32+size,'Short launch-policy command')
        cmd,n=struct.unpack_from('<II',raw,at)
        require(n>=8 and at+n<=32+size,'Invalid launch-policy command')
        if cmd==0x19:
            require(n>=72,'Short launch-policy segment')
            va,span,off,extent=struct.unpack_from('<4Q',raw,at+24)
            require(extent<=span and off+extent<=len(raw),'Unbacked launch-policy segment')
            result.append((va,off,extent))
        at+=n
    require(at==32+size,'Unconsumed launch-policy commands')
    return result


def location(ranges,address,size):
    matches=[off+address-va for va,off,extent in ranges
             if va<=address and address+size<=va+extent]
    require(len(matches)==1,'Launch policy not uniquely file backed')
    return matches[0]


def verify_kernel_policy(raw):
    evidence=json.loads(Path(__file__).with_name('earlyboot-launch-policy.json').read_text())
    ranges=regions(raw);checked={};data={}
    for row in evidence['ranges']:
        at=location(ranges,int(row['address'],16),row['bytes'])
        blob=raw[at:at+row['bytes']]
        require(hashlib.sha256(blob).hexdigest()==row['sha256'],
                'Retained AMFI launch policy changed: '+row['name'])
        checked[row['name']]=row['sha256'];data[row['name']]=blob
    # Check the actual switch dispatch, rather than inferring a category from
    # the numeric c[8] in the failure (that is the policy source, not TC 8).
    require(0xfffffff008eff8bc+struct.unpack_from('<i',data['self_table'],5*4)[0]
            ==0xfffffff008eff9d4,'Wrong category 5 self dispatch')
    require(0xfffffff008effbc8+struct.unpack_from('<i',data['parent_table'],5*4)[0]
            ==0xfffffff008effbf8,'Wrong category 5 parent dispatch')
    words=struct.unpack('<8I',data['system_service_categories'])
    require(words[3]&0xffe0001f==0x52800009 and words[4]&0xffe0001f==0x72a00009,
            'System-service category mask no longer uses reviewed instructions')
    mask=((words[3]>>5)&0xffff)|(((words[4]>>5)&0xffff)<<16)
    require(mask==0x890ba and mask&(1<<5) and not mask&1,'Unexpected system-service categories')
    return dict(category=5,launch_type=1,old_category_zero_accepted=False,
                system_service_category_mask=hex(mask),checked_ranges=checked,
                self_requirement=evidence['self_requirement'],
                parent_requirement=evidence['parent_requirement'],
                amfi_modified=False,hardware_qualified=False)
