from math import pi, sin, cos
from random import choice

from shapely.geometry import Point, Polygon

NE, ENE, ESE, SE, SSE, S, SW, WSW, WNW, NW, NNW, N, NNE = range(13)

# slide 13 of http://www.cs.uu.nl/docs/vakken/gd/steven2.pdf
placements = {NE: 0.000, ENE: 0.070, ESE: 0.100, SE: 0.175, SSE: 0.200,
              S: 0.900, SW: 0.600, WSW: 0.500, WNW: 0.470, NW: 0.400,
              NNW: 0.575, N: 0.800, NNE: 0.150}

class Place:

    def __init__(self, name, font, location, position, radius, **extras):
        self.name = name
        self.location = location
        self.position = position
    
        self.placement = NE
        self.radius = radius
        self.buffer = 2
        
        self._label_shapes = {}      # dictionary of label bounds by placement
        self._mask_shapes = {}       # dictionary of mask shapes by placement
        self._label_footprint = None # all possible label shapes, together
        self._mask_footprint = None  # all possible mask shapes, together
        self._point_shape = None     # point shape for current placement
        
        full_extras = 'placement' in extras \
                  and '_label_shapes' in extras \
                  and '_mask_shapes' in extras \
                  and '_label_footprint' in extras \
                  and '_mask_footprint' in extras \
                  and '_point_shape' in extras
        
        if full_extras:
            # use the provided extras
            self.placement = extras['placement']
            self._label_shapes = extras['_label_shapes']
            self._mask_shapes = extras['_mask_shapes']
            self._label_footprint = extras['_label_footprint']
            self._mask_footprint = extras['_mask_footprint']
            self._point_shape = extras['_point_shape']

        else:
            # fill out the shapes above
            self._populate_shapes(font)

        # label bounds for current placement
        self._label_shape = self._label_shapes[self.placement]

        # mask shape for current placement
        self._mask_shape = self._mask_shapes[self.placement]

    def __repr__(self):
        return '<Place: %s>' % self.name
    
    def __hash__(self):
        return id(self)
    
    def __deepcopy__(self, memo_dict):
        """ Override deep copy to spend less time copying.
        
            Profiling showed that a significant percentage of time was spent
            deep-copying annealer state from step to step, and testing with
            z5 U.S. data shows a 4000% speed increase, so yay.
        """
        extras = dict(placement = self.placement,
                      _label_shapes = self._label_shapes,
                      _mask_shapes = self._mask_shapes,
                      _label_footprint = self._label_footprint,
                      _mask_footprint = self._mask_footprint,
                      _point_shape = self._point_shape)
        
        return Place(self.name, None, self.location, self.position, self.radius, **extras)
    
    def _populate_shapes(self, font):
        """ Set values for self._label_shapes, _footprint_shape, and _footprint_shape_b.
        """
        point = Point(self.position.x, self.position.y)
        point_buffered = point.buffer(self.radius + self.buffer, 3)
        self._point_shape = point.buffer(self.radius, 3)
        
        x, y = self.position.x, self.position.y
        w, h = font.getsize(self.name)
        
        for placement in placements:
            label_shape = point_label_bounds(x, y, w, h, self.radius, placement)
            mask_shape = label_shape.buffer(self.buffer, 2).union(point_buffered)
            
            self._label_shapes[placement] = label_shape
            self._mask_shapes[placement] = mask_shape
    
        unionize = lambda a, b: a.union(b)
        self._label_footprint = reduce(unionize, self._label_shapes.values())
        self._mask_footprint = reduce(unionize, self._mask_shapes.values())
    
    def label(self):
        """ Return a label polygon, the bounds of the current label shape.
        """
        return self._label_shape
    
    def footprint(self):
        """ Return a footprint polygon, the total coverage of all placements.
        """
        return self._label_footprint
    
    def move(self):
        self.placement = choice(placements.keys())
        self._label_shape = self._label_shapes[self.placement]
        self._mask_shape = self._mask_shapes[self.placement]
    
    def placement_energy(self):
        return placements[self.placement]
    
    def overlaps(self, other, reflexive=True):
        overlaps = self._mask_shape.intersects(other.label())
        
        if reflexive:
            overlaps |= other.overlaps(self, False)

        return overlaps

    def can_overlap(self, other, reflexive=True):
        can_overlap = self._mask_footprint.intersects(other.footprint())
        
        if reflexive:
            can_overlap |= other.can_overlap(self, False)

        return can_overlap

def point_label_bounds(x, y, width, height, radius, placement):
    """ Rectangular area occupied by a label placed by a point with radius.
    """
    if placement in (NE, ENE, ESE, SE):
        x += radius + width/2
    
    if placement in (NW, WNW, WSW, SW):
        x -= radius + width/2

    if placement in (NW, NE):
        y -= height/2

    if placement in (SW, SE):
        y += height/2

    if placement in (ENE, WNW):
        y -= height/6

    if placement in (ESE, WSW):
        y += height/6
    
    if placement in (NNE, SSE, NNW):
        _x = radius * cos(pi/4) + width/2
        _y = radius * sin(pi/4) + height/2
        
        if placement in (NNE, SSE):
            x += _x
        else:
            x -= _x
        
        if placement in (SSE, ):
            y += _y
        else:
            y -= _y
    
    if placement == N:
        y -= radius + height / 2
    
    if placement == S:
        y += radius + height / 2
    
    x1, y1 = x - width/2, y - height/2
    x2, y2 = x + width/2, y + height/2
    
    return Polygon(((x1, y1), (x1, y2), (x2, y2), (x2, y1), (x1, y1)))

class Places:

    def __init__(self):
        self.energy = 0.0

        self._places = []    # core list of places
        self._neighbors = {} # dictionary of neighbor sets
        self._moveable = []  # list of only this places that should be moved
        self._indexes = {}   # dictionary of numeric place indexes

    def __iter__(self):
        return iter(self._places)

    def add(self, place):
        self._neighbors[place] = set()
        self._indexes[place] = len(self._indexes) + 1
    
        # calculate neighbors
        for other in self._places:
            if not place.can_overlap(other):
                continue

            self.energy += self._overlap_energy(place, other)

            self._moveable.append(place)
            self._neighbors[place].add(other)
            self._neighbors[other].add(place)

        self.energy += place.placement_energy()
        self._places.append(place)
        
        return self._neighbors[place]

    def _overlap_energy(self, this, that):
        """ Energy of an overlap between two places, if it exists.
        """
        if not this.overlaps(that):
            return 0.0

        a, b = self._indexes[this], self._indexes[that]
        return min(10.0 / a, 10.0 / b)
    
    def move(self):
        place = choice(self._moveable)
        
        for other in self._neighbors[place]:
            self.energy -= self._overlap_energy(place, other)

        self.energy -= place.placement_energy()

        place.move()
        
        for other in self._neighbors[place]:
            self.energy += self._overlap_energy(place, other)

        self.energy += place.placement_energy()