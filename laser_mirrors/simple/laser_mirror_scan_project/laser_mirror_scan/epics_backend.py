from __future__ import annotations

import time
from dataclasses import dataclass


class SimPV:
    def __init__(self, name: str, initial=0):
        self.name = name
        self.value = initial
        self.connected = True
        self.callbacks = []

    def get(self, timeout=None):
        return self.value

    def put(self, value, wait=False, timeout=None):
        self.value = value
        for cb in list(self.callbacks):
            try:
                cb(pvname=self.name, value=value, timestamp=time.time())
            except Exception:
                pass
        return True

    def add_callback(self, cb):
        self.callbacks.append(cb)

    def clear_callbacks(self):
        self.callbacks.clear()


class PVFactory:
    def __init__(self, safe_mode: bool):
        self.safe_mode = safe_mode
        self.cache = {}
        self.PV = None
        if not safe_mode:
            from epics import PV  # type: ignore
            self.PV = PV

    def pv(self, name: str, initial=0):
        if name in self.cache:
            return self.cache[name]
        if self.safe_mode:
            pv = SimPV(name, initial)
        else:
            pv = self.PV(name, connection_timeout=1.0)
        self.cache[name] = pv
        return pv


def safe_float(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


@dataclass
class MotorSnapshot:
    key: str
    base: str
    val: float
    rbv: float
    dmov: int
    movn: int
    desc: str
    egu: str
    stat: str
    sevr: str
    rtyp: str


class EpicsMotor:
    def __init__(self, key: str, base: str, factory: PVFactory):
        self.key = key
        self.base = base
        self.factory = factory
        self.val = factory.pv(base + ".VAL", 0)
        self.rbv = factory.pv(base + ".RBV", 0)
        self.dmov = factory.pv(base + ".DMOV", 1)
        self.movn = factory.pv(base + ".MOVN", 0)
        self.stop_pv = factory.pv(base + ".STOP", 0)
        self.desc = factory.pv(base + ".DESC", key)
        self.egu = factory.pv(base + ".EGU", "steps")
        self.stat = factory.pv(base + ".STAT", "NO_ALARM")
        self.sevr = factory.pv(base + ".SEVR", "NO_ALARM")
        self.rtyp = factory.pv(base + ".RTYP", "motor")

    def snapshot(self) -> MotorSnapshot:
        return MotorSnapshot(
            key=self.key,
            base=self.base,
            val=safe_float(self.val.get(timeout=0.3)),
            rbv=safe_float(self.rbv.get(timeout=0.3)),
            dmov=int(safe_float(self.dmov.get(timeout=0.3), 0)),
            movn=int(safe_float(self.movn.get(timeout=0.3), 0)),
            desc=str(self.desc.get(timeout=0.3)),
            egu=str(self.egu.get(timeout=0.3)),
            stat=str(self.stat.get(timeout=0.3)),
            sevr=str(self.sevr.get(timeout=0.3)),
            rtyp=str(self.rtyp.get(timeout=0.3)),
        )

    def move(self, target_steps: float) -> None:
        self.val.put(float(target_steps), wait=False)
        if self.factory.safe_mode:
            self.movn.put(1)
            self.dmov.put(0)
            self.rbv.put(float(target_steps))
            self.val.put(float(target_steps))
            self.movn.put(0)
            self.dmov.put(1)

    def wait_done(self, timeout_s: float = 30.0, poll_s: float = 0.05) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            try:
                if int(float(self.dmov.get(timeout=0.2))) == 1:
                    return True
            except Exception:
                pass
            time.sleep(poll_s)
        return False

    def stop(self) -> None:
        self.stop_pv.put(1, wait=False)

    def monitor(self, callback) -> None:
        for field, pv in [
            ("VAL", self.val),
            ("RBV", self.rbv),
            ("DMOV", self.dmov),
            ("MOVN", self.movn),
            ("STAT", self.stat),
            ("SEVR", self.sevr),
        ]:
            full = self.base + "." + field

            def cb(pvname=None, value=None, timestamp=None, field=field, full=full, **kwargs):
                callback(self.key, full, value)

            try:
                pv.add_callback(cb)
            except Exception as exc:
                callback(self.key, full, f"<callback error: {exc}>")

    def clear_callbacks(self) -> None:
        for pv in [self.val, self.rbv, self.dmov, self.movn, self.stop_pv, self.stat, self.sevr]:
            try:
                pv.clear_callbacks()
            except Exception:
                pass
