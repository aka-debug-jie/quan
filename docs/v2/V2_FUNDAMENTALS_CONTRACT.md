# V2-B PIT Fundamental Evidence Contract

Status: `BLOCKED_DATA`

V2-B may use `book_to_price`, `return_on_equity` and `momentum_12_1` only
when each observation has an immutable raw-source SHA-256, an effective date,
an official publication date, and an availability date not earlier than that
publication. The observations must bind to a qualified CSI300 PIT report.

The qualification is bidirectional: every PIT member used for a signal must
have all three verified inputs available on that signal date, and every scored
security must have PIT membership evidence. No static current constituent list,
forward-filled fundamental, inferred filing date, or unverified Qlib field can
satisfy this contract.

The initial deterministic score is an equal-weight industry z-score of value,
quality and 12-1 momentum. It is research ranking evidence only until the
Qlib/PIT and fundamental gates are both qualified; it does not authorize a
portfolio, backtest, paper account, or live order.
