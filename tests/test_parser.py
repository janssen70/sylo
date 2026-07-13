from sylo.receiver.parser import parse_syslog


def test_rfc3164_basic():
    raw = b"<34>Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8"
    fields = parse_syslog(raw)
    assert fields.facility == 4
    assert fields.severity == 2
    assert fields.host == "mymachine"
    assert fields.tag == "su"
    assert fields.message == "'su root' failed for lonvick on /dev/pts/8"
    assert not fields.malformed


def test_rfc3164_tag_with_pid():
    raw = b"<13>Jan  1 00:00:00 host sshd[1234]: session opened"
    fields = parse_syslog(raw)
    assert fields.host == "host"
    assert fields.tag == "sshd"
    assert fields.message == "session opened"


def test_rfc5424_basic():
    raw = (
        b"<165>1 2003-10-11T22:14:15.003Z mymachine.example.com evntslog "
        b"- ID47 - An application event log entry"
    )
    fields = parse_syslog(raw)
    facility, severity = divmod(165, 8)
    assert fields.facility == facility
    assert fields.severity == severity
    assert fields.host == "mymachine.example.com"
    assert fields.tag == "evntslog"
    assert "application event log entry" in fields.message
    assert not fields.malformed


def test_malformed_no_pri_never_raises():
    fields = parse_syslog(b"this is not syslog at all")
    assert fields.malformed
    assert fields.facility is None
    assert fields.message == "this is not syslog at all"


def test_empty_input_never_raises():
    fields = parse_syslog(b"")
    assert fields.malformed
    assert fields.message == ""


def test_garbage_bytes_never_raise():
    fields = parse_syslog(b"\xff\xfe<999>\x00\x01\x02garbage")
    assert fields.malformed


def test_truncated_pri_never_raises():
    fields = parse_syslog(b"<12")
    assert fields.malformed
