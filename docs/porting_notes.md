# Porting Notes For `original/betagui.py`

## Python 2 To 3 Issues

- `from Tkinter import *` must become Python 3 `tkinter` imports.
- `from tkFileDialog import *` and `from FileDialog import *` are Python 2 names.
- `print` statements use Python 2 syntax throughout.
- `thread` module import is Python 2 specific and appears unnecessary.
- Mixed tabs and spaces are present in several blocks and may break under stricter parsing or reformatting.
- Unicode literals such as `u"\N{GREEK SMALL LETTER Xi}"` are fine in Python 3 but surrounding Tk code still needs migration.
- Import-time `Tk()` construction is hostile to headless testing and should be delayed.

## Startup Blockers

- `epics` is required at import time because PVs are created immediately.
- `.get()` is called on many PVs during import, so startup depends on live EPICS connectivity.
- `Tk()` is created at import time, so import requires a display-capable Tk environment.
- matplotlib is imported and configured at import time.
- `rc('text', usetex=True)` introduces a LaTeX dependency that may fail on startup.

## Required Dependencies Observed In The Original

- Python 2 runtime
- Tk / Tkinter
- matplotlib
- numpy
- scipy
- pyepics
- a working EPICS environment with the referenced PVs reachable
- likely a working LaTeX installation because `usetex=True` is enabled

## Suspicious Helpers

### `set_Isextupole_slowly()`

- uses undefined name `aself`
- mixes PV-name and PV-object usage
- creates `pvSextupole` and never uses it
- appears incomplete / stale

### `BPDM()`

- intended to read BPM waveform but currently returns zeros
- GUI orbit plot is therefore not a real orbit diagnostic

### `set_sext_degauss()`

- always writes `pvS1P1` and `pvS1P2` at the end even if they are not in `sextlist`
- I did not find an active caller in the main workflow

## Missing Functions / Symbols

- `setcur(...)` is called in `start_poly()` but is not defined anywhere in the file.
- `fine_bump_status` appears in a `global` statement but is never defined.
- `mea_poly_status`, `scan4D_status`, `mat_status`, `bump_dim`, `cor_option`, and `Bbuf` are used as globals with implicit lifecycle inside GUI callbacks; some are only created if specific UI paths are taken.

## Likely Bugs And Typos

- Shebang is `#!usr/bin/python` instead of `#!/usr/bin/python`.
- Duplicate imports: `threading`, `thread`, and `curve_fit` are imported twice.
- `delayMeasTune` input is read in `MeaChrom()` and never used.
- `nmeasurements` is decremented inside the RF loop, changing behavior across scan points.
- `np.delete(fbuf[l],np.argmax(...),np.argmin(...))` is not valid use of `np.delete`; third positional argument is `axis`, not a second index.
- `print 'initial rf frequency is:',frf0,' MHz'` conflicts with other comments treating RF as kHz or Hz.
- `pvOptTab` is created globally, but `MeaChrom()` reads a fresh `epics.PV('MLSOPCCP:actOptRmpTblSet')` instead of reusing it.
- `if  cor_option==1and flag2D3D:` is valid tokenization but poor style and easy to misread.
- `start_bump()` steps sextupoles by `-1` and then `+1` from the shifted value; it does not explicitly restore the original starting current after each dimension.
- `start_poly()` references `pvS2P2`, whereas main correction logic often uses split channels `pvS2P2K` and `pvS2P2L`.
- `bumpdataS=bumpdataS-bumpdataS[-float(paras[i][1].get())-1,:]` uses a float index and is almost certainly broken.
- `Sc` and `Sd` in `gen_scan_tab()` use the minimum value for both linspace endpoints, so they do not actually scan.
- `ndd=int(Scanentries[2][2].get())` probably should use row 3 instead of row 2.
- Several variables and comments use inconsistent spellings, such as `pvwhitenosie`, `varibales`, `measuremnts`, `coeffecient`, `setupoles`.

## Stale / Dead / Low-Confidence Code

- commented-out alternate tune PVs
- commented-out BPM waveform decode
- `set_Isextupole_slowly()` looks unused and incomplete
- `set_sext_degauss()` looks unused in the main GUI path
- commented-out sextupole write calls in `gen_scan_tab()` indicate a half-disabled feature
- `docs` mention of a “fine bump” workflow is not matched by complete executable code

## Runtime Risks

- import can hang or fail if PVs are unavailable
- GUI updates are performed from worker threads, which is unsafe in Tkinter
- EPICS writes are active by default from the GUI
- machine-state restoration is incomplete if a run is interrupted at the wrong point
- matrix inversion has no error handling for singular or ill-conditioned matrices
- measurement logic assumes tune and RF reads always return numeric values
- file dialogs are used deep inside worker flows, mixing user interaction and background work
- offline testing is effectively impossible in the current structure

## Minimal Safe Porting Direction

- keep the numerical workflow and GUI layout close to the original
- move EPICS access behind a thin adapter
- delay PV creation until runtime instead of import
- make import succeed without live EPICS, Tk, or matplotlib
- preserve write-capable operations but label them clearly and keep them opt-in
- keep matrix file format simple and compatible
- isolate enough measurement logic to support mock/offline tests
