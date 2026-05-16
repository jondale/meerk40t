from .cutobject import CutObject


class RotaryAdvanceCut(CutObject):
    """
    Advance the rotary axis by a given number of motor steps.

    Used by the rotary strip stage in CutPlan to interleave rotary
    motion between raster slices. The driver executes this by calling
    its rotary_move_relative() method.
    """

    def __init__(self, steps, speed=None, settings=None, passes=1, parent=None, color=None):
        """
        @param steps: Number of motor steps to advance (signed).
        @param speed: Optional max motor speed override.
        """
        CutObject.__init__(
            self,
            (0, 0),
            (0, 0),
            settings=settings,
            passes=passes,
            parent=parent,
            color=color,
        )
        self.steps = steps
        self.speed = speed
        self.first = True
        self.last = True

    def reversible(self):
        return False

    def reverse(self):
        pass

    def generate(self):
        if self.speed is not None:
            yield "rotary_move_relative", self.steps, self.speed
        else:
            yield "rotary_move_relative", self.steps
        yield "rotary_wait"
