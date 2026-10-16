#!/usr/bin/env python3
"""Plot arrival-window beam-stack spectra for P38 at YKA and ILAR."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from obspy import read


EVENTS = (
    ("2006 event", "HD2006-05-29_2dstack.mseed", "tab:green"),
    ("2015 event", "HD2015-05-24_2dstack.mseed", "tab:red"),
)
# pro7 selects R index 4 and T index 5 on an 11-by-11 PKIKP beam grid.
BEAM_INDEX = 4 * 11 + 5
TIME_WINDOW_S = (-5.0, 20.0)
SPECTRUM_BAND_HZ = (0.5, 3.0)


def read_beam_stack(path: Path) -> tuple[np.ndarray, np.ndarray, float]:
    trace = read(path)[BEAM_INDEX]
    time = np.arange(trace.stats.npts) * trace.stats.delta - 50.0
    return time, np.asarray(trace.data, dtype=float), float(trace.stats.delta)


def spectrum(data: np.ndarray, dt: float) -> tuple[np.ndarray, np.ndarray]:
    """Return amplitude spectrum relative to its in-band maximum, in dB."""
    tapered = data * np.hanning(data.size)
    nfft = 1 << (data.size - 1).bit_length()
    freqs = np.fft.rfftfreq(nfft, dt)
    amplitude = np.abs(np.fft.rfft(tapered, nfft))
    band = (freqs >= SPECTRUM_BAND_HZ[0]) & (freqs <= SPECTRUM_BAND_HZ[1])
    amplitude /= amplitude[band].max()
    return freqs, 20.0 * np.log10(np.maximum(amplitude, 1e-8))


def plot_array(root: Path, mode: str, array: str, output: Path) -> None:
    folder = root / "cases" / "without_relative_offset" / mode / "intermediate"
    fig, (waveform_axis, spectrum_axis) = plt.subplots(
        2, 1, figsize=(8, 7), constrained_layout=True
    )
    for label, filename, color in EVENTS:
        time, data, dt = read_beam_stack(folder / filename)
        selected = (time >= TIME_WINDOW_S[0]) & (time <= TIME_WINDOW_S[1])
        windowed = data[selected]
        waveform_axis.plot(
            time[selected], windowed / np.max(np.abs(windowed)), color=color,
            linewidth=1.1, label=label,
        )
        frequencies, db = spectrum(windowed, dt)
        in_band = (frequencies >= SPECTRUM_BAND_HZ[0]) & (frequencies <= SPECTRUM_BAND_HZ[1])
        spectrum_axis.plot(frequencies[in_band], db[in_band], color=color, linewidth=1.2)

    waveform_axis.axvline(0.0, color="0.5", linewidth=0.7)
    waveform_axis.axhline(0.0, color="0.7", linewidth=0.7)
    waveform_axis.set(
        title=f"P38 {array} PKIKP beam stacks, {TIME_WINDOW_S[0]:g} to {TIME_WINDOW_S[1]:g} s",
        xlabel="Time relative to explicit event reference (s)",
        ylabel="Amplitude (each event normalized)",
        ylim=(-1.1, 1.1),
    )
    waveform_axis.legend(loc="upper right")
    waveform_axis.grid(alpha=0.2)

    spectrum_axis.set(
        title="Amplitude spectra (each spectrum normalized within displayed band)",
        xlabel="Frequency (Hz)", ylabel="Relative amplitude (dB)",
        xlim=SPECTRUM_BAND_HZ, ylim=(-50, 3),
    )
    spectrum_axis.grid(alpha=0.2)
    fig.savefig(output, dpi=220)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plot_array(args.run_root, "yka_40s", "YKA", args.output_dir / "P38_YKA_event_spectra.png")
    plot_array(args.run_root, "ilar_40s", "ILAR", args.output_dir / "P38_ILAR_event_spectra.png")


if __name__ == "__main__":
    main()
