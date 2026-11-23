# myron desktop runtime repair

This change fixes source-level gaps found after the confirmed desktop boot on
45008031354. Phone validation is still required; host tests are not a phone result.

* Presentation pairs chosen display-scale=3, artwork-scale=3 and 2556 phone
  artwork. Actual GOP size/stride, FT3683 normalized coordinates, original
  display submission/retirement gates, N104 security donor and synchronous
  backboard compositor remain unchanged. Final embedded ADT checks use the
  same values; only MobileGestalt answer caches are removed from the newly prepared seed. The status-bar placement still needs a phone comparison.
* A separate consumer-control HID service reports physical Power (usage 0x30).
  It uses the retained 207-slot IOHIDDevice ABI already used by FT3683, with
  its own timer/workloop, 20 ms samples and two-sample debounce. Reads use
  the stock myron SPMI v8 EE0 observer and PMK8850 SID0 PON 0x1310 bit7.
  Boot-held input is suppressed until released; a failed hardware transaction
  stops further MMIO polling and releases a delivered key. No PMIC reset,
  pinmux, interrupt routing or suspend policy is changed. SoC deep sleep is
  not implemented by this HID change.
* Data is backed by a bounded write-through UFS overlay instead of being
  forced volatile. Root signature, selected unixnu partition, GPT CRC,
  compiled geometry and exact Data seed hash remain required. Payload pages
  use FUA before bitmap publication; cache sync is forwarded under the Data
  lock. I/O errors prevent further writes. No Android userdata target exists.
* The new extent includes a pending/ready initialization marker. This permits
  first use of the previously unused unixnu gap even if freed Android blocks
  contain nonzero residue. A recognized overlay of another seed or one with
  invalid metadata is never reset. A ready marker with damaged overlay fails
  closed. Boot arguments cannot silently erase it. Reuse the exact seed for
  updates; automatic migration to a regenerated APFS seed is not implemented.

For the recorded 32 GiB unixnu geometry and current 1 GiB seed, the whole
allocation is LBA 257522166 through 257784319 (4096-byte units). The signed
root ends below it; the policy carrier and log are in the separate retained
tail. Geometry is derived and rechecked, not hardcoded as write authorization.
The first marker consumes one block; the upstream overlay begins at 257522167.

`check.py` exercises real callbacks, range overflow/overlap refusals, write
failure closure, overlay reopen/foreign-seed refusal and power input filtering.
Upstream RamBlock sparse/direct/persistence algorithm tests remain enabled.

## Platform power and app migration follow-up

The pinned ArmDTPlatform has no device power override. Its inherited final
kernel vtable uses IODTPlatformExpert::haltRestart and the initial
PE_halt_restart pointer is zero. `platform-power.patch` adds normal halt/reset
handling through the DT's exact SMC/HVC conduit, cached during configuration.
PSCI SYSTEM_OFF/RESET is invoked only at XNU's platform shutdown boundary,
after its existing storage and driver notifications. Unknown conduits refuse;
panic, paging and other notifications keep their original path. A returning
firmware is an error, including an unexpected zero return. No PMIC address is
guessed. Source dispatch tests pass; final native compilation and phone power
removal remain unverified.

An existing app-copy marker no longer skips the narrowly scoped migration
request: only the byte-exact synthetic preference created by this port is
eligible for removal. Changed userland preferences remain intact. The source
test exercises both first-copy and already-copied paths and error propagation.
The persistent boot snapshot also retains the existing copy stage, failure,
errno and current path, so a late capture can distinguish copying from app
registration. A selected host inventory does not establish phone installation.
