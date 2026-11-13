"""Execute emitted pre-MMU markers, check live registers and rendered pixels."""
import argparse,json,struct,sys,unittest
from pathlib import Path
import unicorn as u
from unicorn import arm64_const as r
import probe
p=argparse.ArgumentParser();p.add_argument('--probe',type=Path,required=True);a,rest=p.parse_known_args()
report=json.loads((a.probe/'probe.json').read_text());labels={k:int(v,16) for k,v in report['labels'].items()}
b=(a.probe/'kernel.macho').read_bytes();ss=probe.segments(b)
PA=0x8c0004000;VA=0xfffffff007004000;SLIDE=PA-VA
FB=0xfc800000;ARGS=0x8c6000000;ROW=4800;HEIGHT=2608
font=[14,17,19,21,25,17,14,4,12,4,4,4,4,14,14,17,1,2,4,8,31,30,1,1,14,1,1,30,2,6,10,18,31,2,2,31,16,16,30,1,1,30,14,16,16,30,17,17,14,31,1,2,4,8,8,8,14,17,17,14,17,17,14,14,17,17,15,1,1,14,14,17,17,31,17,17,17,30,17,17,30,17,17,30,14,17,16,16,16,17,14,30,17,17,17,17,17,30,31,16,16,30,16,16,31,31,16,16,30,16,16,16]
def check_pixels(data,value):
    expected=bytearray(len(data))
    for d,char in enumerate(f'{value:016x}'):
        n=int(char,16)
        for y in range(7):
            for x in range(5):
                px=b'\xff'*4 if font[n*7+y]&(1<<(4-x)) else b'\0'*4
                for sy in range(4):
                    at=(y*4+sy)*ROW+(d*24+x*4)*4
                    expected[at:at+16]=px*4
    assert data==expected,'Rendered phase differs or writes escaped glyphs'
class Markers(unittest.TestCase):
    def test_markers_preserve_live_registers_and_flags(self):
        for label,phase,end in [('ProbeEntry',0x2710,probe.FIRST),('LowMark',0x2711,labels['LowResume']),('TablesMark',0x2712,labels['TablesResume']),('KeysMark',0x2713,labels['KeysResume']),('MmuMark',0x2714,labels['MmuResume'])]:
            with self.subTest(label=label):
                em=u.Uc(u.UC_ARCH_ARM64,u.UC_MODE_ARM)
                lo=(probe.CAVE+SLIDE)&~4095;em.mem_map(lo,0x4000)
                off=probe.offset(ss,probe.CAVE,report['observer_bytes']);em.mem_write(probe.CAVE+SLIDE,b[off:off+report['observer_bytes']])
                em.mem_map(ARGS,4096);em.mem_map(FB,0xc00000)
                args=bytearray(4096);struct.pack_into('<6Q',args,0x28,FB,1,ROW,1200,HEIGHT,32);em.mem_write(ARGS,bytes(args))
                em.mem_write(labels['Context']+SLIDE,struct.pack('<Q',ARGS))
                regs=[getattr(r,'UC_ARM64_REG_X'+str(i)) for i in range(29)]+[r.UC_ARM64_REG_X29,r.UC_ARM64_REG_X30]
                values=[0x123400+i*0x100 for i in range(31)];values[0]=ARGS
                for reg,v in zip(regs,values):em.reg_write(reg,v)
                em.reg_write(r.UC_ARM64_REG_NZCV,0xa0000000)
                em.emu_start(labels[label]+SLIDE,end+SLIDE,count=200000)
                self.assertEqual(em.reg_read(r.UC_ARM64_REG_PC),end+SLIDE)
                for i,reg in enumerate(regs):
                    if i!=18:self.assertEqual(em.reg_read(reg),values[i],(label,i))
                self.assertEqual(em.reg_read(r.UC_ARM64_REG_NZCV),0xa0000000)
                self.assertEqual(struct.unpack('<Q',em.mem_read(labels['Context']+SLIDE+8,8))[0],phase)
                check_pixels(bytes(em.mem_read(FB+ROW*(HEIGHT//4),ROW*28)),phase)
    def test_wrong_image_rejected(self):
        with self.assertRaisesRegex(ValueError,'Wrong retained kernel'):probe.inspect(b)
    def test_branch_range(self):
        with self.assertRaises(ValueError):probe.branch(0,1<<27)
        with self.assertRaises(ValueError):probe.branch(0,3)
if __name__=='__main__':unittest.main(argv=[sys.argv[0]]+rest)
