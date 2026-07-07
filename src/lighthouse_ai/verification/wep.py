"""Words of Estimative Probability (WEP) bands.

Per ICD-203 / Sherman Kent's tradition. Lighthouse uses five bands; every
claim emitted carries one. Probability-to-band mapping uses Kent's midpoints.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WEPBand:
    name: str
    low: float
    high: float
    label: str

    def __contains__(self, p: float) -> bool:
        return (
            self.low <= p < self.high
            if self.name != "almost_certain"
            else (self.low <= p <= self.high)
        )


WEP_BANDS: tuple[WEPBand, ...] = (
    WEPBand("remote", 0.00, 0.10, "remote"),
    WEPBand("unlikely", 0.10, 0.40, "unlikely"),
    WEPBand("even", 0.40, 0.60, "even chance"),
    WEPBand("likely", 0.60, 0.90, "likely"),
    WEPBand("almost_certain", 0.90, 1.01, "almost certain"),
)


def band_for_probability(p: float) -> WEPBand:
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"probability out of [0,1]: {p}")
    for b in WEP_BANDS:
        if p in b:
            return b
    return WEP_BANDS[-1]


def parse_band(name: str) -> WEPBand:
    name = name.strip().lower().replace(" ", "_")
    for b in WEP_BANDS:
        if b.name == name:
            return b
    raise KeyError(f"unknown WEP band: {name!r}")
