# Three applications of the shared signal-processing core

[System architecture](../architecture/system/README.md) | [Editable algorithm specification](../algorithm/README.md)

T-RECAP is a tunable spectral reduction experiment. The same FFT, threshold and IFFT/WOLA core can operate on different real signal representations. The RF input frontend converts recorded I/Q into the real intermediate-frequency samples expected by that core. This folder connects that architecture to concrete users, actual data and measurable outcomes.

The scenarios below explain possible uses. The measurements determine how far each scenario has been demonstrated. The software does not know whether a weak component is unwanted noise or important information.

| Application and scenario | Demonstrated result | Important tradeoff | Open the evidence |
| --- | --- | --- | --- |
| Indoor movement sensing when GPS is unavailable. Evaluate a step-counting component on recorded acceleration with added noise | At threshold 10^10, noisy extra detections fall from 989 to 360 | Missed events rise from 232 to 279. This is not a complete indoor positioning system | [Step counts, traces, source files and all five thresholds](accelerometer/README.md) |
| A receiver monitoring intermittent sensor transmissions. Suppress weak background components while retaining messages | Recorded background power falls by about 44% at 10^10 in two fixtures with their messages retained. A generated 10 dB AWGN case gains about 5.40 dB SNR on hardware at 10^9 | At 10^11, one recorded message is lost. Digital power suppression does not identify the physical source of the noise | [RF spectra, decoding outcomes and audible demonstration](rf/README.md) |
| A student preparing narration and music for a smaller archive. Compare spectral cleanup and FLAC output before choosing a threshold | Physical audio output gives 4.11% and 15.97% extra FLAC size reduction at 10^8 and 10^10 relative to the same quantized threshold-0 baseline | Detail is lost. Encoding-time changes are inconsistent. Separate software noise tests include worse cases | [Audio spectra, original and processed playback, FLAC files and evaluation](audio/README.md) |

## What to look for in the demo

1. Start with the original source and its sample rate, units and provenance.
2. Inspect threshold 0 to separate representation conversion and quantization from threshold effects.
3. Increase the threshold while keeping gain and the downstream algorithm fixed.
4. Compare useful behavior as well as bytes or background level. For example, count missed steps and lost messages rather than only how clean a plot looks.
5. Listen only where the mapping is meaningful. Audio is directly playable. The RF listening demo maps an envelope into an audible tone and is explicitly labeled as sonification. Acceleration is shown in physical units and event timing.

## Two outputs, different benefits

Y is the reconstructed real waveform. These pages use it for step detection, RF recovery and audio encoding. TSP1 carries dense or sparse spectral powers without phase. A sparse-aware host consumer can process fewer retained entries and transfer fewer bytes. A dense neural network or a fixed-length decoder does not automatically do less work because some bins were removed.

The [project overview results](../project_overview/README.md) include the separate downstream spectral-consumer timing measurements. Those should not be conflated with the FLAC encoder, pedometer or protocol decoder results in this folder.

## Evidence and source access

These pages publish archived hardware measurements and clearly labeled software experiments. This documentation update did not perform a new physical run. Numerical tables, source identities, media and plot generators are included in each application folder. Original datasets remain linked to their providers where a redistribution license has not been established.

The audio listening page works offline after cloning the repository. RF has a separate local listening page. GitHub can render the Markdown and PNG plots, while its file preview does not execute arbitrary HTML. Download the repository to use the interactive playback controls.

Run the publication audit from the repository root:

```sh
python phase2/docs/applications/check_bundle.py
```

This checks committed file identities, local links and the published audio sample bindings. It does not rerun the physical experiments, prove the interpretation of a plot or measure electrical power.
