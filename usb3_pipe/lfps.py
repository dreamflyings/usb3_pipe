from math import ceil

from migen import *
from migen.genlib.cdc import MultiReg
from migen.genlib.misc import WaitTimer

# Constants/Helpers --------------------------------------------------------------------------------

lfps_clk_freq_min = 1/100e-9
lfps_clk_freq_max = 1/20e-9

class LFPSTiming:
    def __init__(self, t_typ=None, t_min=None, t_max=None):
        self.t_typ = t_typ
        self.t_min = t_min
        self.t_max = t_max
        assert t_min is not None
        assert t_max is not None
        self.range = (t_min, t_max)

class LFPS:
    def __init__(self, burst, repeat=None, cycles=None):
        self.burst  = burst
        self.repeat = repeat
        self.cycles = None

def ns_to_cycles(clk_freq, t):
    return ceil(t*clk_freq)

# LFPS Definitions ---------------------------------------------------------------------------------

# TODO: add LFPS Handshake timings

PollingLFPSBurst  = LFPSTiming(t_typ=1.0e-6,  t_min=0.6e-6, t_max=1.4e-6)
PollingLFPSRepeat = LFPSTiming(t_typ=10.0e-6, t_min=6.0e-6, t_max=14.0e-6)
PollingLFPS       = LFPS(burst=PollingLFPSBurst, repeat=PollingLFPSRepeat)

PingLFPSBurst     = LFPSTiming(t_typ=None,     t_min=40.0e-9,  t_max=200.0e-9)
PingLFPSRepeat    = LFPSTiming(t_typ=200.0e-3, t_min=160.0e-3, t_max=240.0e-3)
PingLFPS          = LFPS(burst=PingLFPSBurst, repeat=PingLFPSRepeat, cycles=2)

ResetLFPSBurst    = LFPSTiming(t_typ=100.0e-3, t_min=80.0e-3,  t_max=120.0e-3)
ResetLFPS         = LFPS(burst=ResetLFPSBurst)

U1ExitLFPSBurst   = LFPSTiming(t_typ=None, t_min=300.0e-9, t_max=900.0e-9) # FIXME: t_max=900.0e-9/2.0e-6?
U1ExitLFPS        = LFPS(burst=U1ExitLFPSBurst)

U2LFPSBurst       = LFPSTiming(t_typ=None, t_min=80.0e-3, t_max=2.0e-3)
U2LFPS            = LFPS(burst=U2LFPSBurst)

LoopbackExitLFPS  = U2LFPS

U3WakeupLFPSBurst = LFPSTiming(t_typ=None, t_min=80.0e-3, t_max=10.0e-3)
U3WakeupLFPS      = LFPS(burst=U3WakeupLFPSBurst)

# LFPS Receiver ------------------------------------------------------------------------------------

class LFPSReceiver(Module):
    def __init__(self, sys_clk_freq):
        self.idle    = Signal() # i
        self.polling = Signal() # o

        # # #

        # Idle Resynchronization -------------------------------------------------------------------
        idle          = Signal()
        self.specials += MultiReg(self.idle, idle)

        # Polling LFPS Detection -------------------------------------------------------------------
        burst_cycles  = ns_to_cycles(sys_clk_freq, PollingLFPS.burst.t_typ)
        repeat_cycles = ns_to_cycles(sys_clk_freq, PollingLFPS.repeat.t_typ)
        self.count = count = Signal(max=max(burst_cycles, repeat_cycles))
        self.found = found = Signal()

        self.submodules.fsm = fsm = FSM(reset_state="TBURST")
        fsm.act("TBURST",
            If(count == 0,
                If(idle == 0,
                    NextValue(count, burst_cycles - 1),
                ).Else(
                    NextValue(count, repeat_cycles - burst_cycles - 1),
                    NextState("TREPEAT")
                )
            ).Else(
                NextValue(count, count - 1)
            ),
            If(found & (idle == 0),
                self.polling.eq(1),
                NextValue(found, 0)
            ),
        )
        fsm.act("TREPEAT",
            NextValue(count, count - 1),
            If((count == 0) | (idle == 0),
                NextValue(found, (count == 0)),
                NextValue(count, burst_cycles - 1),
                NextState("TBURST")
            )
        )

# LFPS Transmitter ---------------------------------------------------------------------------------

class LFPSTransmitter(Module):
    def __init__(self, sys_clk_freq, lfps_clk_freq):
        self.idle            = Signal()   # o
        self.pattern         = Signal(40) # o

        # # #

        # Burst clock generation -------------------------------------------------------------------
        assert lfps_clk_freq >= lfps_clk_freq_min
        assert lfps_clk_freq <= lfps_clk_freq_max
        clk = Signal()
        clk_timer = WaitTimer(ceil(sys_clk_freq/(2*lfps_clk_freq)) - 1)
        self.submodules += clk_timer
        self.comb += clk_timer.wait.eq(~clk_timer.done)
        self.sync += If(clk_timer.done, clk.eq(~clk))

        # Polling LFPS generation ------------------------------------------------------------------
        burst_cycles  = ns_to_cycles(sys_clk_freq, PollingLFPS.burst.t_typ)
        repeat_cycles = ns_to_cycles(sys_clk_freq, PollingLFPS.repeat.t_typ)
        burst_timer   = WaitTimer(burst_cycles)
        repeat_timer  = WaitTimer(repeat_cycles)
        self.submodules += burst_timer, repeat_timer
        self.comb += [
            burst_timer.wait.eq(~repeat_timer.done),
            repeat_timer.wait.eq(~repeat_timer.done),
        ]

        # Output -----------------------------------------------------------------------------------
        self.comb += [
            self.idle.eq(burst_timer.done),
            self.pattern.eq(Replicate(clk, 40)),
        ]
