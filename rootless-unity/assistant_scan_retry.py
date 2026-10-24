"""Only a verified no-action cached-list scan can be repeated."""
def readonly_list_changed(operation,value):
    if operation!='open' or type(value) is not dict or value.get('state')!='stopped' or value.get('identity') is not None:return False
    n=value.get('diagnostic')
    return (type(n) is dict and n.get('stage')=='navigation-stopped'
        and n.get('error')=='selection-count-changed' and n.get('phase')=='scan'
        and n.get('metadata_checkpoint')=='ready' and n.get('selection_checkpoint')=='model-list'
        and n.get('action_attempted') is False and n.get('action_completed') is False
        and n.get('destination_verified') is False)
