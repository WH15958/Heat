interface PrimingRecord {
  prime_volume_a?: number
  prime_volume_b?: number
  prime_cycles?: number
  prime_drain_seconds?: number
  prime_drain_flow?: number
  prime_drain_factor?: number
  prime_extra_seconds?: number
  drain_flow?: number
}

// Legacy values are restored for display only; never create execution eligibility.
export function primingDrainForDisplay(record: PrimingRecord) {
  return {
    prime_drain_seconds: record.prime_drain_seconds ??
      ((record.prime_volume_a ?? 2) + (record.prime_volume_b ?? 2)) * (record.prime_cycles ?? 2) *
      (record.prime_drain_factor ?? 1.2) / (record.drain_flow ?? 1) * 60 + (record.prime_extra_seconds ?? 0),
    prime_drain_flow: record.prime_drain_flow ?? record.drain_flow ?? 1,
  }
}
