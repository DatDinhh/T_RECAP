# Audio sources and licenses

[Application](README.md) | [Listen](listen.html)

The upstream audio is separately licensed from T-RECAP software. Each title, source and license below applies to its prepared and processed derivatives. Piano media is restricted to noncommercial use under CC BY-NC 3.0. No endorsement by the artists or dataset authors is implied.

## Speech A

The Age of Chivalry / Chapter 18: Perceval / Read by Anders Lankford
From the LibriSpeech SLR12 collection: https://www.openslr.org/12/
CC-BY 4.0 https://creativecommons.org/licenses/by/4.0/

- [Pinned original .txt file](https://raw.githubusercontent.com/librosa/data/38f4b06556fa0ff1acda5e677d8ba05d1bc0fff0/audio/3436-172162-0000.txt), SHA-256 `8cf4b20e148c4366205bc607f447c169256e945d62c64ead43d0a4dfa7d3ab98`
- [Pinned original .hq.ogg file](https://raw.githubusercontent.com/librosa/data/38f4b06556fa0ff1acda5e677d8ba05d1bc0fff0/audio/3436-172162-0000.hq.ogg), SHA-256 `8e034529f2f171c7e5e772df6eccc2d169183c39605b45b351c2bfabddf14162`

## Speech B

Sense and Sensibility / Chapter 18 / Jane Austen / Read by Heather Barnett
From the LibriSpeech SLR12 collection: https://www.openslr.org/12/
CC-BY 4.0 https://creativecommons.org/licenses/by/4.0/

- [Pinned original .txt file](https://raw.githubusercontent.com/librosa/data/38f4b06556fa0ff1acda5e677d8ba05d1bc0fff0/audio/198-209-0000.txt), SHA-256 `c5bf58b2a4aa0d6bf1e6051690312f3238960d455776a6d37e469d80db1da167`
- [Pinned original .hq.ogg file](https://raw.githubusercontent.com/librosa/data/38f4b06556fa0ff1acda5e677d8ba05d1bc0fff0/audio/198-209-0000.hq.ogg), SHA-256 `6a8d2c16e56dcb27b7f5fe5aa99bfd26b4722a6dabca1968eff951b456936514`

## Piano

Pistachio Ice Cream Ragtime by The Piano Lady (Lena Orsa)
https://freesound.org/people/lena_orsa/sounds/442789/
CC-BY NC 3.0: https://creativecommons.org/licenses/by-nc/3.0/

- [Pinned original .txt file](https://raw.githubusercontent.com/librosa/data/38f4b06556fa0ff1acda5e677d8ba05d1bc0fff0/audio/442789__lena-orsa__happy-music-pistachio-ice-cream-ragtime.txt), SHA-256 `99f9c44368918572ac154ae4a2fec4020d1d4bb418ae7bf241864916d68f9d04`
- [Pinned original .hq.ogg file](https://raw.githubusercontent.com/librosa/data/38f4b06556fa0ff1acda5e677d8ba05d1bc0fff0/audio/442789__lena-orsa__happy-music-pistachio-ice-cream-ragtime.hq.ogg), SHA-256 `1cc83b775e640a8dd409da9e29f5b5e0124bc5ec9bb4fda975919d31d1d893b8`

## Jazz

Vibe Ace by Kevin MacLeod is licensed under a Creative Commons Attribution License.
From the Free Music Archive: https://freemusicarchive.org/music/Kevin_MacLeod/Jazz_Sampler/Vibe_Ace
CC-BY https://creativecommons.org/licenses/by/3.0/

- [Pinned original .txt file](https://raw.githubusercontent.com/librosa/data/38f4b06556fa0ff1acda5e677d8ba05d1bc0fff0/audio/Kevin_MacLeod_-_Vibe_Ace.txt), SHA-256 `6c71e0525cb0452ea74c6d6f5fde6fa1e221223db7b2aa35b9914b98367ee7b9`
- [Pinned original .hq.ogg file](https://raw.githubusercontent.com/librosa/data/38f4b06556fa0ff1acda5e677d8ba05d1bc0fff0/audio/Kevin_MacLeod_-_Vibe_Ace.hq.ogg), SHA-256 `73d6443ef90a7c022f164e5aa90e56c2291585930b39b1656d0765abbc1f1779`

## Changes made to the recordings

FLAC experiment derivatives use the first 8 seconds, mono channel averaging, resampling to 48 kHz, a common fixed gain of 0.5, PCM16 preparation and signed 12-bit quantization. Hardware derivatives additionally apply thresholding and IFFT/WOLA, fixed alignment and expansion back into a PCM16 container. FLAC uses preset 5. No per-output normalization is used.

Denoising derivatives use a separate frozen level preparation, synthetic noise and the existing fixed-point software algorithm. The listening page labels these separately. Its reference, noisy and processed versions share a common playback conversion within each example.

The repository provides links to the full original upstream files and includes only the prepared excerpts and their derivatives for this educational comparison.
