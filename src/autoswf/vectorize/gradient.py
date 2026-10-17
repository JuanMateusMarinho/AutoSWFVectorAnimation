"""Fit one SWF gradient (radial or linear, up to 8 stops) to a soft layer's coverage, for layers the user wants as
gradient fills instead of posterized steps."""
import numpy as np

from autoswf.model.geometry import Matrix
from autoswf.model.shape import GradientFill, GradientStop

GRADIENT_SIDE = 1638.4                 # Flash's gradient square, px
STOPS = 8


def _stops(position: np.ndarray, alpha: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean alpha at STOPS evenly spaced positions in 0..1 (empty bins are interpolated)."""
    centers = np.linspace(0, 1, STOPS)
    half = 0.5 / (STOPS - 1)
    values = np.array([alpha[np.abs(position - c) <= half].mean() if (np.abs(position - c) <= half).any() else np.nan
                       for c in centers])
    ok = ~np.isnan(values)
    values = np.interp(centers, centers[ok], values[ok]) if ok.any() else np.zeros(STOPS)
    return centers, values


def _gradient(kind: str, color, matrix: Matrix, centers: np.ndarray, values: np.ndarray) -> GradientFill:
    r, g, b = (int(v) for v in color[:3])
    stops = tuple(GradientStop(int(round(c * 255)), (r, g, b, int(round(np.clip(v, 0, 1) * 255))))
                  for c, v in zip(centers, values))
    return GradientFill(kind, stops, matrix)


def _radial(color, xy: np.ndarray, alpha: np.ndarray):
    center = np.average(xy, axis=0, weights=alpha)
    d = xy - center
    cov = (d * alpha[:, None]).T @ d / alpha.sum()
    eigval, eigvec = np.linalg.eigh(cov)
    sigma = np.sqrt(np.maximum(eigval, 1e-6))
    proj = d @ eigvec / sigma
    reach = float(np.percentile(np.hypot(*proj.T), 99.5)) or 1.0
    radii = sigma * reach
    position = np.hypot(*(d @ eigvec / radii).T)
    centers, values = _stops(position, alpha)
    model = np.interp(np.minimum(position, 1), centers, values)
    k = radii / (GRADIENT_SIDE / 2)
    m = Matrix(eigvec[0, 0] * k[0], eigvec[1, 0] * k[0], eigvec[0, 1] * k[1], eigvec[1, 1] * k[1], center[0], center[1])
    return _gradient("radial", color, m, centers, values), float(np.sqrt(np.mean((model - alpha) ** 2)))


def _linear(color, xy: np.ndarray, alpha: np.ndarray, field: np.ndarray, mask: np.ndarray):
    gy, gx = np.gradient(field)
    g = np.array([gx[mask].mean(), gy[mask].mean()])
    if np.hypot(*g) < 1e-9:
        g = np.linalg.svd(xy - xy.mean(axis=0), full_matrices=False)[2][0]
    u = -g / np.hypot(*g)                              # from the strong end towards the faint end
    t = xy @ u
    t0, t1 = np.percentile(t, 2), np.percentile(t, 98)
    span = max(t1 - t0, 1e-6)
    position = np.clip((t - t0) / span, 0, 1)
    centers, values = _stops(position, alpha)
    model = np.interp(position, centers, values)
    k = span / GRADIENT_SIDE
    mid = u * (t0 + t1) / 2 + (xy.mean(axis=0) - u * (xy.mean(axis=0) @ u))
    m = Matrix(u[0] * k, u[1] * k, -u[1] * k, u[0] * k, mid[0], mid[1])
    return _gradient("linear", color, m, centers, values), float(np.sqrt(np.mean((model - alpha) ** 2)))


def fit_gradient(color, alpha: np.ndarray) -> tuple[GradientFill, float]:
    """The better of a radial and a linear gradient for `alpha` (H x W, 0..1) in the array's pixel space (pixel
    centers), and its RMS alpha error over the covered pixels."""
    mask = alpha > 2 / 255
    ys, xs = np.nonzero(mask)
    xy = np.stack([xs + 0.5, ys + 0.5], axis=1).astype(np.float64)
    weights = alpha[mask].astype(np.float64)
    fits = [_radial(color, xy, weights), _linear(color, xy, weights, alpha, mask)]
    return min(fits, key=lambda f: f[1])
