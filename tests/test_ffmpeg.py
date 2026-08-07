import pytest

from pocyeah.ffmpeg import build_encode_args


def test_build_encode_args_has_rawvideo_stdin_input_and_libx264_output():
    args = build_encode_args(640, 480, 30, "out.mov", "ffmpeg")
    assert args[0] == "ffmpeg"
    # raw RGB frames arrive on stdin at a fixed size and rate
    assert "-f" in args and args[args.index("-f") + 1] == "rawvideo"
    assert args[args.index("-pix_fmt") + 1] == "rgb24"
    assert "640x480" in args
    assert args[args.index("-i") + 1] == "-"
    # widely-playable encoded output, silent, overwrite
    assert "libx264" in args
    assert "-an" in args
    assert args[-1] == "out.mov"
    assert "-y" in args


def test_build_encode_args_honours_custom_ffmpeg_binary():
    args = build_encode_args(2, 2, 30, "o.mov", "/opt/ffmpeg")
    assert args[0] == "/opt/ffmpeg"


def test_build_encode_args_rejects_odd_dimensions():
    with pytest.raises(ValueError, match="even"):
        build_encode_args(641, 480, 30, "o.mov")
    with pytest.raises(ValueError, match="even"):
        build_encode_args(640, 481, 30, "o.mov")


def test_build_encode_args_rejects_nonpositive_size_and_fps():
    with pytest.raises(ValueError):
        build_encode_args(0, 480, 30, "o.mov")
    with pytest.raises(ValueError):
        build_encode_args(640, 480, 0, "o.mov")
