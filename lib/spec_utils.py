import os

import chainer.functions as F
import librosa
import numpy as np


def crop_and_concat(h1, h2, concat=True):
    # s_freq = (h2.shape[2] - h1.shape[2]) // 2
    # e_freq = s_freq + h1.shape[2]
    s_time = (h2.shape[3] - h1.shape[3]) // 2
    e_time = s_time + h1.shape[3]
    h2 = h2[:, :, :, s_time:e_time]
    if concat:
        return F.concat([h1, h2])
    else:
        return h2


def calc_spec(X, hop_length, phase=False):
    n_fft = (hop_length - 1) * 2
    spec_left = librosa.stft(X[0], n_fft, hop_length=hop_length)
    spec_right = librosa.stft(X[1], n_fft, hop_length=hop_length)
    spec = np.asarray([spec_left, spec_right])

    if phase:
        mag = np.abs(spec)
        phase = np.exp(1.j * np.angle(spec))
        return mag, phase
    else:
        mag = np.abs(spec)
        return mag


def mask_uninformative(mask, ref, min_range=64, thres=0.4):
    fade_area = 32
    idx = np.where(ref.mean(axis=(0, 1)) < thres)[0]
    starts = np.insert(idx[np.where(np.diff(idx) != 1)[0] + 1], 0, idx[0])
    ends = np.append(idx[np.where(np.diff(idx) != 1)[0]], idx[-1])
    uninformative = np.where(ends - starts > min_range)[0]
    if len(uninformative) > 0:
        starts = starts[uninformative]
        ends = ends[uninformative]
        old_e = None
        for s, e in zip(starts, ends):
            if old_e is not None and s - old_e < fade_area:
                s = old_e - fade_area * 2
            elif s != 0:
                start_mask = mask[:, :, s:s + fade_area]
                np.clip(start_mask + np.linspace(0, 1, fade_area), 0, 1,
                        out=start_mask)
            if e != mask.shape[2]:
                end_mask = mask[:, :, e - fade_area:e]
                np.clip(end_mask + np.linspace(1, 0, fade_area), 0, 1,
                        out=end_mask)
            mask[:, :, s + fade_area:e - fade_area] = 1
            old_e = e
    return mask


def align_wave_head_and_tail(a, b, sr):
    a_mono = a[:, :sr * 2].sum(axis=0)
    b_mono = b[:, :sr * 2].sum(axis=0)
    a_mono -= a_mono.mean()
    b_mono -= b_mono.mean()
    offset = len(a_mono) - 1
    delay = np.argmax(np.correlate(a_mono, b_mono, 'full')) - offset

    if delay > 0:
        a = a[:, delay:]
    else:
        b = b[:, np.abs(delay):]
    if a.shape[1] < b.shape[1]:
        b = b[:, :a.shape[1]]
    else:
        a = a[:, :b.shape[1]]

    return a, b


def cache_or_load(mix_path, inst_path, sr, hop_length):
    _, ext = os.path.splitext(mix_path)
    spec_mix_path = mix_path.replace(ext, '.npy')
    spec_inst_path = inst_path.replace(ext, '.npy')

    if os.path.exists(spec_mix_path) and os.path.exists(spec_inst_path):
        X = np.load(spec_mix_path)
        y = np.load(spec_inst_path)
    else:
        X, _ = librosa.load(
            mix_path, sr, False, dtype=np.float32, res_type='kaiser_fast')
        y, _ = librosa.load(
            inst_path, sr, False, dtype=np.float32, res_type='kaiser_fast')
        X, _ = librosa.effects.trim(X)
        y, _ = librosa.effects.trim(y)
        X, y = align_wave_head_and_tail(X, y, sr)

        X = calc_spec(X, hop_length)
        y = calc_spec(y, hop_length)

        _, ext = os.path.splitext(mix_path)
        np.save(spec_mix_path, X)
        np.save(spec_inst_path, y)

    coeff = np.max([X.max(), y.max()])
    return X / coeff, y / coeff


def spec_to_wav(mag, phase, hop_length):
    spec = mag * phase
    wav_left = librosa.istft(spec[0], hop_length=hop_length)
    wav_right = librosa.istft(spec[1], hop_length=hop_length)
    wav = np.asarray([wav_left, wav_right])
    return wav
