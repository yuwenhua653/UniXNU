"""Regression-check category-zero rejection against a real packaged kernel."""
import argparse,json,sys,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'myron-gpu'))
from earlyboot_launch_policy import verify_kernel_policy,regions,location

p=argparse.ArgumentParser();p.add_argument('--kernel',type=Path,required=True)
a,rest=p.parse_known_args()

class LaunchPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=a.kernel.read_bytes()
        cls.ranges=regions(cls.raw)
        cls.evidence=json.loads((ROOT/'myron-gpu/earlyboot-launch-policy.json').read_text())

    def test_actual_retained_policy_and_parent(self):
        r=verify_kernel_policy(self.raw)
        self.assertEqual(r['category'],5)
        self.assertFalse(r['old_category_zero_accepted'])
        self.assertEqual(r['self_requirement'],{'validation-category':1})
        self.assertTrue(r['parent_requirement']['$or']['is-init-proc'])
        self.assertFalse(r['amfi_modified'])

    def test_changed_policy_or_der_is_rejected(self):
        for row in self.evidence['ranges']:
            with self.subTest(region=row['name']):
                bad=bytearray(self.raw)
                at=location(self.ranges,int(row['address'],16),row['bytes'])
                bad[at+row['bytes']//2]^=1
                with self.assertRaisesRegex(ValueError,'Retained AMFI launch policy changed'):
                    verify_kernel_policy(bad)

    def test_invalid_kernel_does_not_pass(self):
        for raw in (b'',self.raw[:32],bytes(len(self.raw[:128]))):
            with self.assertRaises(ValueError):verify_kernel_policy(raw)

if __name__=='__main__':unittest.main(argv=[sys.argv[0],*rest])
