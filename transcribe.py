import subprocess
import tempfile
from pathlib import Path
from config import WHISPER_MODEL, AUDIO_SEGMENT_MINUTES

_model = None
_model_name = None


def _get_model():
    global _model, _model_name
    if _model is None or _model_name != WHISPER_MODEL:
        from faster_whisper import WhisperModel
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        _model_name = WHISPER_MODEL
    return _model


def transcribe_audio(audio_path: Path, language: str = "zh", progress_callback=None) -> str:
    size_mb = audio_path.stat().st_size / (1024 * 1024)
    if size_mb > 50:
        return _transcribe_chunked(audio_path, language, progress_callback)
    return _transcribe_single(audio_path, language, progress_callback)


def _transcribe_single(audio_path: Path, language: str, progress_callback=None) -> str:
    model = _get_model()
    segments, info = model.transcribe(str(audio_path), language=language, beam_size=5)
    total_duration = info.duration if info and hasattr(info, 'duration') else 0
    parts = []
    for seg in segments:
        parts.append(seg.text)
        if progress_callback and total_duration > 0:
            pct = min(1.0, seg.end / total_duration)
            progress_callback(pct, f"{seg.end:.0f}/{total_duration:.0f}秒")
    return "".join(parts)


def _transcribe_chunked(audio_path: Path, language: str, progress_callback=None) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        chunk_pattern = str(Path(tmpdir) / "chunk_%03d.mp3")
        segment_seconds = AUDIO_SEGMENT_MINUTES * 60
        subprocess.run([
            "ffmpeg", "-i", str(audio_path),
            "-f", "segment", "-segment_time", str(segment_seconds),
            "-c", "copy", chunk_pattern,
        ], capture_output=True)

        chunks = sorted(Path(tmpdir).glob("chunk_*.mp3"))
        parts = []
        for i, chunk in enumerate(chunks):
            if progress_callback:
                progress_callback((i + 0.5) / len(chunks), f"分段 {i+1}/{len(chunks)}")
            text = _transcribe_single(chunk, language)
            parts.append(text)
            if progress_callback:
                progress_callback((i + 1) / len(chunks), f"分段 {i+1}/{len(chunks)} 完成")
        return "\n".join(parts)


def get_audio_duration(audio_path: Path) -> int:
    result = subprocess.run(
        ["ffmpeg", "-i", str(audio_path)],
        capture_output=True, text=True,
    )
    import re
    match = re.search(r"Duration: (\d+):(\d+):(\d+)", result.stderr)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
        return h * 3600 + m * 60 + s
    return 0
