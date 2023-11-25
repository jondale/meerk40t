from .toolpointlistbuilder import PointListTool
from meerk40t.svgelements import Polyline

class PolylineTool(PointListTool):
    """
    Polyline Drawing Tool.

    Adds a polyline with two or more clicks.
    """

    def __init__(self, scene):
        PointListTool.__init__(self, scene)

    def create_node(self):
        if len(self.point_series) > 1:
            polyline = Polyline(*self.point_series)
            elements = self.scene.context.elements
            node = elements.elem_branch.add(
                shape=polyline,
                type="elem polyline",
                stroke_width=elements.default_strokewidth,
                stroke=elements.default_stroke,
                fill=elements.default_fill,
            )
            if elements.classify_new:
                elements.classify([node])
            self.notify_created(node)
    def point_added(self):
        # Nothing particular to do here
        return

    def draw_points(self, gc, points):
        gc.StrokeLines(points)
