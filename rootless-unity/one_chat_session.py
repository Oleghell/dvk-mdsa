"""Public diagnostics for the manual one-shot mode: codes/counters only."""
from one_chat_preview import report as preview_report
from one_chat_actions import report_fields
from one_chat_send import checked_diagnostic


def report(outcome=None, *, failure=False, send_state='not-reserved', transcript_saved=False, submission_check=None):
    if transcript_saved is not None and type(transcript_saved) is not bool:
        raise ValueError('Invalid local-save flag')
    result=preview_report(outcome,failure=failure)
    if outcome is None and not failure and send_state!='not-reserved':result['status']='manual-send-result'
    if submission_check is not None:result['submission_check']=checked_diagnostic(submission_check)
    result.update(report_fields(send_state))
    result.update(mode='one-bound-owned-test-chat-manual-one-shot',
                  manual_send_available=True,local_transcript_saved=transcript_saved,
                  local_transcript_plaintext=transcript_saved,message_text_in_report=False,
                  transcript_order_verified=False)
    return result
