"""Bounded original-cache call and register evidence; no runtime assumptions."""
from bisect import bisect_right
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM


def exact_symbol(cache, address):
    image = cache.image_for(address)
    if image is None:
        return None
    symbol = cache.symbol_for(address, image, strict=False)
    if not symbol or symbol.get('address') != hex(address):
        return None
    name = symbol.get('name')
    return name if name and name != '<redacted>' else None


def call_entry(cache, decoder, address):
    """Record short thunks and decode only proven v5 pointer-chain members."""
    rows = []; seen = set()
    for _ in range(4):
        if address in seen:
            break
        seen.add(address)
        row = dict(address=hex(address), exact_symbol=None)
        rows.append(row)
        try:
            row['exact_symbol'] = exact_symbol(cache, address)
            if row['exact_symbol']:
                break
            ops = list(decoder.disasm(cache.read(address, 32, executable=True)[0], address))
            row['instructions'] = [(hex(op.address-address), op.mnemonic, op.op_str) for op in ops]
            pages = {}; pointers = {}; target = None
            for op in ops:
                operands = op.operands
                if op.mnemonic == 'b' and operands[0].type == ARM64_OP_IMM:
                    target = operands[0].imm
                    break
                if op.mnemonic == 'adrp':
                    pages[operands[0].reg] = operands[1].imm
                    pointers.pop(operands[0].reg, None)
                elif op.mnemonic == 'add' and len(operands) == 3 and operands[2].type == ARM64_OP_IMM:
                    value = pages.get(operands[1].reg)
                    pages.pop(operands[0].reg, None); pointers.pop(operands[0].reg, None)
                    if value is not None:
                        pages[operands[0].reg] = value + (operands[2].imm << operands[2].shift.value)
                elif op.mnemonic == 'ldr' and operands[1].type == ARM64_OP_MEM:
                    mem = operands[1].mem
                    page = pages.get(mem.base)
                    pages.pop(operands[0].reg, None); pointers.pop(operands[0].reg, None)
                    if page is not None:
                        slot = page + mem.disp
                        chain = cache.pointer_chain(slot, 0)
                        if chain.get('chain_member'):
                            pointers[operands[0].reg] = int(chain['unsigned_runtime_target'], 16)
                            row.setdefault('pointer_targets', []).append(dict(
                                slot=hex(slot), target=chain['unsigned_runtime_target'],
                                static_chain_only=True))
                elif op.mnemonic in ('br', 'braa', 'braaz', 'brab', 'brabz'):
                    target = pointers.get(operands[0].reg)
                    break
                else:
                    # Do not propagate an address across a register overwrite.
                    _, writes = op.regs_access()
                    for reg in writes:
                        pages.pop(reg, None); pointers.pop(reg, None)
                if op.mnemonic in ('ret', 'retab', 'bl', 'blr'):
                    break
            if target is None:
                break
            address = target
        except (ValueError, RuntimeError, OSError) as error:
            row['unresolved'] = str(error)[:200]
            break
    return rows


def collect(cache, image, starts, names, decoder, flow):
    """Keep all symbol names, selected lifecycle methods and exact call entries."""
    base = image['address']
    mandatory = {0x2667c0, 0x6bbd4, 0x6a39c}
    selected = {base + offset for offset in mandatory}
    for address, labels in names.items():
        if any(('DataStore' in name or 'PosterBoard' in name) and any(
                word in name for word in (' init', 'dataStore', 'sharedInstance', 'load', 'create', 'setUp'))
               for name in labels):
            selected.add(address)
    ordered = sorted(selected, key=lambda address: (address-base not in mandatory, address))
    rows = []; calls = set()
    for address in ordered[:48]:
        index = bisect_right(starts, address)-1
        if index < 0 or index+1 >= len(starts) or starts[index] != address:
            continue
        end = starts[index+1]; high = min(end, address+2048)
        ops = list(decoder.disasm(cache.read(address, high-address, executable=True)[0], address))
        rows.append(dict(offset=hex(address-base), names=sorted(names.get(address, ())),
            function_bytes=end-address, truncated=high<end,
            instructions=[(hex(op.address-address), op.mnemonic, op.op_str) for op in ops],
            references=flow(cache, image, decoder, names, address, high, string_limit=512)))
        for op in ops:
            if op.mnemonic in ('bl', 'b') and op.operands[0].type == ARM64_OP_IMM:
                target = op.operands[0].imm
                if not address <= target < end:
                    calls.add(target)
    return dict(symbols=[(hex(address-base), sorted(labels)) for address, labels in sorted(names.items())],
        functions=rows, omitted_functions=max(0, len(ordered)-48),
        call_entries=[call_entry(cache, decoder, address) for address in sorted(calls)[:256]],
        omitted_calls=max(0, len(calls)-256), runtime_observation=False,
        raw_image_bytes_exported=False, pointer_authentication_executed=False)
