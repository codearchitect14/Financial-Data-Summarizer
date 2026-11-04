const NOT_AVAILABLE = '—'

export function formatPrice(value: number | null | undefined, currency = 'USD'): string {
  if (value == null) return NOT_AVAILABLE
  return new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(value)
}

/** Large amounts such as $478.8B. */
export function formatCompact(value: number | null | undefined, currency = 'USD'): string {
  if (value == null) return NOT_AVAILABLE
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    notation: 'compact',
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value)
}

export function formatSigned(value: number | null | undefined, currency = 'USD'): string {
  if (value == null) return NOT_AVAILABLE
  return `${value >= 0 ? '+' : '−'}${formatPrice(Math.abs(value), currency)}`
}

export function formatPercent(value: number | null | undefined): string {
  if (value == null) return NOT_AVAILABLE
  return `${value >= 0 ? '+' : '−'}${Math.abs(value).toFixed(2)}%`
}

export function formatRange(
  low: number | null | undefined,
  high: number | null | undefined,
  currency = 'USD',
): string {
  if (low == null || high == null) return NOT_AVAILABLE
  return `${formatPrice(low, currency)} – ${formatPrice(high, currency)}`
}

/** Dates from filings have no time zone, so read them as written. */
export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return NOT_AVAILABLE
  return new Date(`${isoDate.slice(0, 10)}T00:00:00Z`).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

export function formatDateTime(isoDateTime: string | null | undefined, withSeconds = false): string {
  if (!isoDateTime) return NOT_AVAILABLE
  return new Date(isoDateTime).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: withSeconds ? '2-digit' : undefined,
    timeZoneName: 'short',
  })
}
