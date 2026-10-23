"""Selected conversation only; no UI actions or persistent image files."""
from one_chat_probe import identity
from assistant_store import StateError
from assistant_contact_photo import Device,png_size

def capture_chat(executable,folder,who,cancelled=lambda:False,*,device_factory=Device,binder=None):
    from one_chat_device import capture
    binder=capture if binder is None else binder
    who=identity(who)
    def verify():
        if cancelled():raise StateError('cancelled')
        value=binder(executable,folder,cancelled,None)
        if identity(value['identity'])!=who or value.get('messages') is not None:
            raise StateError('exit-photo-identity-mismatch')
    verify()
    device=device_factory(executable,folder,cancelled)
    image=device.screen();png_size(image)
    verify()
    return image
