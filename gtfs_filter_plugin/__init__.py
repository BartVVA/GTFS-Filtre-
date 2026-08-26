def classFactory(iface):
    from .gtfs_filter_plugin import GtfsFilterPlugin
    return GtfsFilterPlugin(iface)
