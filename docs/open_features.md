# Open Features And Follow-Up Work

This file is the short operational backlog for the repo after the Python 3
porting work.

## High Priority

| Item | Why it matters | Current state |
| --- | --- | --- |
| Real control-room validation | Confirms that the legacy PV profile and restored workflows behave correctly on-machine | Not yet done in this repo |
| Live BPM orbit readout | Makes the orbit plot useful instead of a zero placeholder | Not implemented because the legacy code already had it disabled |
| Operator-facing deployment instructions | Needed before handoff to control-room users | Basic checklist exists, can still be tightened after first tests |

## Medium Priority

| Item | Why it matters | Current state |
| --- | --- | --- |
| Better input validation in the GUI | Prevents bad numeric entries from reaching write paths | Basic logging exists, but field-level validation is still light |
| Optional logging of measurement sessions | Useful for reproducibility and post-mortem analysis | Not yet added |
| On-machine smoke test checklist | Makes first-use safer for operators | Partly covered in runtime docs |

## Lower Priority

| Item | Why it matters | Current state |
| --- | --- | --- |
| More realistic mock physics | Better offline confidence for future changes | Current model is only plausible, not calibrated |
| Expanded test coverage for GUI callbacks | Helps maintenance | Core logic is tested more than widget behavior |
| GitLab Pages or Wiki publishing | Improves discoverability for users and maintainers | Repo docs are ready to be organized for that |

## Recommended Next Development Order

1. Test the clean control-room launcher in read-only live mode.
2. Validate the main measurement and reset flows with operators.
3. Confirm the restored secondary scan workflow against real expectations.
4. Only then decide whether BPM readout or additional polish is worth doing.
