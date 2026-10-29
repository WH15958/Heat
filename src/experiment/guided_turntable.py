"""Guided-batch compatibility wrapper for shared bottle coordination."""
from src.experiment.turntable_sequence import TurntableSequence

POLL_SECONDS = 0.1


class GuidedTurntable(TurntableSequence):
    stop_message = "批次停止已取消转盘操作"

    @property
    def poll_seconds(self):
        return POLL_SECONDS

    async def prepare_start(self):
        self._check_claimed()
        self._check_running()
        control = self.control
        with control.gate:
            generation = control.generation

        def prepare():
            self._check_running()
            return control.prepare_guided_start(self.owner, generation)

        self.needs_stop = True
        summary = await self._call(prepare)
        self._check_running()
        self._publish(summary)
