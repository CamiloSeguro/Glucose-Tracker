from dataclasses import dataclass, fields

MGDL_PER_MMOL = 18.0


@dataclass(frozen=True)
class GlucoseSettings:
    """Plugin-wide settings. Thresholds are always stored in mg/dL."""

    unit:       str  = "mgdl"   # "mgdl" | "mmol"
    urgent_low: int  = 54
    low:        int  = 70
    high:       int  = 180
    very_high:  int  = 250
    alerts:     bool = True

    @classmethod
    def from_global(cls, data: dict) -> "GlucoseSettings":
        """Build from StreamDock global settings, ignoring unknown or invalid keys."""
        defaults = cls()
        values = {}
        for f in fields(cls):
            raw = data.get(f.name)
            if raw is None or raw == "":
                continue
            try:
                if f.type in (int, "int"):
                    values[f.name] = int(float(raw))
                elif f.type in (bool, "bool"):
                    values[f.name] = raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "on")
                else:
                    values[f.name] = str(raw)
            except (TypeError, ValueError):
                pass
        s = cls(**{**defaults.__dict__, **values})
        if s.unit not in ("mgdl", "mmol"):
            s = cls(**{**s.__dict__, "unit": "mgdl"})
        if not (s.urgent_low < s.low < s.high < s.very_high):
            # Nonsense thresholds would make every reading "urgent"; fall back
            s = cls(unit=s.unit, alerts=s.alerts)
        return s

    def format_value(self, mgdl: float | None) -> str:
        if mgdl is None:
            return "---"
        if self.unit == "mmol":
            return f"{mgdl / MGDL_PER_MMOL:.1f}"
        return str(int(round(mgdl)))

    def format_delta(self, delta_mgdl: float | None) -> str:
        if delta_mgdl is None:
            return ""
        if self.unit == "mmol":
            d = delta_mgdl / MGDL_PER_MMOL
            return "±0.0" if abs(d) < 0.05 else f"{d:+.1f}"
        d = int(round(delta_mgdl))
        return "±0" if d == 0 else f"{d:+d}"

    @property
    def unit_label(self) -> str:
        return "mmol/L" if self.unit == "mmol" else "mg/dL"
