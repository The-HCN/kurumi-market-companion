"""Local notification policy; independent of news fetching and manual reading."""
MODES = {'all': '全部消息', 'important': '重要消息', 'manual': '仅手动查看'}


def should_announce(item, settings):
    if settings.get('muted'):
        return False
    mode = settings.get('notification_mode', 'all')
    if mode == 'manual':
        return False
    if mode == 'important':
        return bool(item.get('important') or item.get('priority') == 'alert' or
                    item.get('source', '').startswith('真实到价提醒'))
    return True
