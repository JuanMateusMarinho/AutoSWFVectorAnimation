"""Boundary chains of a label image: the pixel edges ("cracks") between different labels, walked into chains that
run between junctions. Each chain separates exactly two labels and is stored once, so both regions share it and a
planar map built from the chains can never leave a gap or an overlap."""
from dataclasses import dataclass

import numpy as np

R, D, L, U = 1, 2, 4, 8
STEP = {R: (1, 0), D: (0, 1), L: (-1, 0), U: (0, -1)}
OPPOSITE = {R: L, L: R, D: U, U: D}


@dataclass(frozen=True)
class Chain:
    points: np.ndarray       # N x 2 lattice points, image px (x right, y down); closed chains repeat the first point
    left: int                # label on the left of the walking direction (-1 = empty)
    right: int               # label on the right (y down) — SWF FillStyle1
    closed: bool


def boundary_chains(labels: np.ndarray) -> list[Chain]:
    h, w = labels.shape
    p = np.full((h + 2, w + 2), -1, np.int64)
    p[1:-1, 1:-1] = labels
    # lattice vertex (x, y) of the padded grid; horizontal crack (x..x+1, y) lies between pixels p[y-1, x], p[y, x];
    # vertical crack (x, y..y+1) between p[y, x-1], p[y, x]
    horizontal = np.zeros((h + 3, w + 3), bool)
    horizontal[1:h + 2, 0:w + 2] = p[0:h + 1, :] != p[1:h + 2, :]
    vertical = np.zeros((h + 3, w + 3), bool)
    vertical[0:h + 2, 1:w + 2] = p[:, 0:w + 1] != p[:, 1:w + 2]
    exits = np.zeros((h + 3, w + 3), np.uint8)
    exits |= np.where(horizontal, R, 0).astype(np.uint8)
    exits[:, 1:] |= np.where(horizontal[:, :-1], L, 0).astype(np.uint8)
    exits |= np.where(vertical, D, 0).astype(np.uint8)
    exits[1:, :] |= np.where(vertical[:-1, :], U, 0).astype(np.uint8)
    degree = sum((exits >> bit) & 1 for bit in range(4))
    node = degree >= 3

    def sides(x: int, y: int, d: int) -> tuple[int, int]:
        if d == R:
            return int(p[y - 1, x]), int(p[y, x])
        if d == L:
            return int(p[y, x - 1]), int(p[y - 1, x - 1])
        if d == D:
            return int(p[y, x]), int(p[y, x - 1])
        return int(p[y - 1, x - 1]), int(p[y - 1, x])

    def walk(x: int, y: int, d: int) -> tuple[list[tuple[int, int]], int, int]:
        points = [(x, y)]
        left, right = sides(x, y, d)
        while True:
            exits[y, x] &= 15 ^ d
            dx, dy = STEP[d]
            x, y = x + dx, y + dy
            exits[y, x] &= 15 ^ OPPOSITE[d]
            points.append((x, y))
            rest = int(exits[y, x])
            if node[y, x] or rest == 0:
                return points, left, right
            d = rest & -rest

    chains = []
    for closed in (False, True):                 # chains between junctions first; what is left are closed loops
        ys, xs = np.nonzero(exits if closed else node)
        for y, x in zip(ys.tolist(), xs.tolist()):
            while exits[y, x]:
                d = int(exits[y, x]) & -int(exits[y, x])
                points, left, right = walk(x, y, d)
                chains.append(Chain(np.array(points, np.float64) - 1, left, right, closed))
    return chains
