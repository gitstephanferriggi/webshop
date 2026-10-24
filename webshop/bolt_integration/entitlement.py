"""Optional Integration Hub gate; accepted-order completion remains available."""


def new_work_allowed(settings):
    import frappe
    if 'integration_hub' not in frappe.get_installed_apps():
        return True
    reporter = frappe.get_single('Integration Reporter Settings')
    if not reporter.get('licence_enforcement'):
        return True
    try:
        from integration_hub.licence_agent import new_work_allowed as allowed
        return allowed(settings.provider_id, settings.environment) is True
    except Exception:
        return False


def require_new_work(settings):
    if not new_work_allowed(settings):
        import frappe
        frappe.throw('Integration licence is inactive or cannot be verified. Contact your integration provider. Already accepted orders can still be completed.')
