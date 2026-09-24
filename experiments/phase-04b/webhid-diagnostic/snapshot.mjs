// Pure metadata projection. Never open the device or transfer HID reports.
export function snapshotCollection(collection) {
  return {
    usagePage: collection.usagePage,
    usage: collection.usage,
    inputReports: (collection.inputReports ?? []).map(report => report.reportId),
    outputReports: (collection.outputReports ?? []).map(report => report.reportId),
    featureReports: (collection.featureReports ?? []).map(report => report.reportId),
    children: (collection.children ?? []).map(snapshotCollection),
  };
}

export function snapshotDevice(device) {
  if (device.vendorId !== 0x258A || device.productId !== 0x010C) {
    throw new Error('Выбранное устройство не 258A:010C');
  }
  return {
    vendorId: device.vendorId,
    productId: device.productId,
    productName: device.productName,
    collections: (device.collections ?? []).map(snapshotCollection),
  };
}
