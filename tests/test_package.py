def test_version_is_exposed():
    from ducta import __version__

    assert isinstance(__version__, str)
    assert __version__
