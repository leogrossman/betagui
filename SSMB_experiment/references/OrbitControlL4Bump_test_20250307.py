# coding: utf-8

# Original control-room notebook export copied into SSMB_experiment for
# reference while developing the experimental bump-lab tooling.

from epics import PV
from time import sleep


# bump definition:
#
# Bump({'HS1P2K3RP:setCur': 0.03226,'HS3P1L4RP:setCur': 0.014116,
#       'HS3P2L4RP:setCur': 0.014123,'HS1P1K1RP:setCur': 0.031103,
#       'MCLKHGP:setFrq': -2.305})

steerers = [
    PV('HS1P2K3RP:setCur'),
    PV('HS3P1L4RP:setCur'),
    PV('HS3P2L4RP:setCur'),
    PV('HS1P1K1RP:setCur'),
]
steererfactors = [0.03226, 0.014116, 0.014123, 0.031103]

for steerer in steerers:
    print(steerer.get())

BPMs = [
    PV('BPMZ1K1RP:rdX'),
    PV('BPMZ1L2RP:rdX'),
    PV('BPMZ1K3RP:rdX'),
    PV('BPMZ1L4RP:rdX'),
]

for BPM in BPMs:
    print(BPM.get())

freqctrlenable = PV('MCLKHGP:ctrl:enable')
freqctrlenable.get()

gainpv = PV('AKC11VP')
enablepv = PV('AKC10VP')
refpv = PV('AKC12VP')
deadbandpv = PV('AKC13VP')


def bump_steerers(amount):
    for steerer, f in zip(steerers, steererfactors):
        old = steerer.get()
        steerer.put(old + amount * f)


def get_bpm_avg():
    return sum([BPM.get() for BPM in BPMs]) / 4


get_bpm_avg()

refpv.put(get_bpm_avg())


def get_corrector_step(verbose=True):
    gain = gainpv.get()
    ref = refpv.get()
    deadband = deadbandpv.get()
    orbit = get_bpm_avg()
    diff = ref - orbit
    if verbose:
        print(orbit)
        print(ref, gain, deadband)
        print(diff)
    if abs(diff) > deadband:
        return gain * diff
    return 0


get_corrector_step()

freqctrlenable.put(0)
enablepv.put(1)
sleep(1)
while enablepv.get() != 0 and freqctrlenable.get() == 0:
    step = get_corrector_step(verbose=False)
    if step != 0:
        print('\raction:', step, '              ', end='')
        bump_steerers(step)
    sleep(0.5)
enablepv.put(0)
