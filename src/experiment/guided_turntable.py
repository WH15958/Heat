"""Guided-batch compatibility wrapper for shared bottle coordination."""
from src.experiment.turntable_sequence import TurntableSequence

POLL_SECONDS = 0.1


class GuidedTurntable(TurntableSequence):
    stop_message = "批次停止已取消转盘操作"

    @property
    def poll_seconds(self):
        return POLL_SECONDS
