/**
 * Small generated-style client for the preferred v1 resource operations.
 *
 * The host application supplies its authenticated request function.  This
 * keeps the contract client independent of Vue, React, fetch wrappers, and
 * token storage while making route migrations explicit and type checked.
 */
export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
};

export type ApiRequest = <T>(path: string, options?: RequestOptions) => Promise<T>;

export class MyOTAClient {
  constructor(private readonly request: ApiRequest) {}

  getAwardAssetContent<T = unknown>(id: string): Promise<T> {
    return this.request<T>(`/v1/awards/assets/${encodeURIComponent(id)}/content`);
  }

  putAwardAssetContent<T = unknown>(id: string, content: Blob, mediaType: string): Promise<T> {
    return this.request<T>(`/v1/awards/assets/${encodeURIComponent(id)}/content`, { method: 'PUT', body: content, headers: { 'Content-Type': mediaType } });
  }

  createAwardPreview<T = unknown>(body: unknown): Promise<T> {
    return this.request<T>('/v1/awards/previews', { method: 'POST', body });
  }


  patchProgramme<T = unknown>(slug: string, body: unknown): Promise<T> {
    return this.request<T>(`/v1/programmes/${encodeURIComponent(slug)}`, { method: 'PATCH', body, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }

  assignProgrammeEntityCategory<T = unknown>(slug: string, categoryCode: string): Promise<T> {
    return this.request<T>(`/v1/programmes/${encodeURIComponent(slug)}/entity-types/${encodeURIComponent(categoryCode)}`, { method: 'PUT', body: {}, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }

  unassignProgrammeEntityCategory<T = unknown>(slug: string, categoryCode: string): Promise<T> {
    return this.request<T>(`/v1/programmes/${encodeURIComponent(slug)}/entity-types/${encodeURIComponent(categoryCode)}`, { method: 'DELETE', body: {}, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }

  patchProgrammeContent<T = unknown>(slug: string, contentId: string, body: unknown): Promise<T> {
    return this.request<T>(`/v1/programmes/${encodeURIComponent(slug)}/content/${encodeURIComponent(contentId)}`, { method: 'PATCH', body, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }

  patchProgrammePolicyDraft<T = unknown>(slug: string, draftId: string, body: unknown): Promise<T> {
    return this.request<T>(`/v1/programmes/${encodeURIComponent(slug)}/policy-drafts/${encodeURIComponent(draftId)}`, { method: 'PATCH', body, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }

  patchIdentityAccount<T = unknown>(accountId: string, body: unknown): Promise<T> {
    return this.request<T>(`/v1/identity/accounts/${encodeURIComponent(accountId)}`, { method: 'PATCH', body, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }

  createIdentityRole<T = unknown>(body: unknown): Promise<T> {
    return this.request<T>('/v1/identity/roles', { method: 'POST', body, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }

  patchIdentityRole<T = unknown>(roleCode: string, body: unknown): Promise<T> {
    return this.request<T>(`/v1/identity/roles/${encodeURIComponent(roleCode)}`, { method: 'PATCH', body, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }

  patchGeodataEntityMetadata<T = unknown>(entityId: string, body: unknown, version?: number): Promise<T> {
    return this.request<T>(`/v1/geodata/entities/${encodeURIComponent(entityId)}`, { method: 'PATCH', body, headers: { 'Idempotency-Key': crypto.randomUUID(), ...(version === undefined ? {} : { 'If-Match': `"${version}"` }) } });
  }

  postGeodataEntityLocationEnrichmentRequest<T = unknown>(entityId: string, body: unknown, version?: number): Promise<T> {
    return this.request<T>(`/v1/geodata/entities/${encodeURIComponent(entityId)}/location-enrichment-requests`, { method: 'POST', body, headers: { 'Idempotency-Key': crypto.randomUUID(), ...(version === undefined ? {} : { 'If-Match': `"${version}"` }) } });
  }

  putGeodataEntityGeometry<T = unknown>(entityId: string, body: unknown, version?: number): Promise<T> {
    return this.request<T>(`/v1/geodata/entities/${encodeURIComponent(entityId)}/geometry`, { method: 'PUT', body, headers: { 'Idempotency-Key': crypto.randomUUID(), ...(version === undefined ? {} : { 'If-Match': `"${version}"` }) } });
  }

  putGeodataEntityCategories<T = unknown>(entityId: string, body: unknown, version?: number): Promise<T> {
    return this.request<T>(`/v1/geodata/entities/${encodeURIComponent(entityId)}/categories`, { method: 'PUT', body, headers: { 'Idempotency-Key': crypto.randomUUID(), ...(version === undefined ? {} : { 'If-Match': `"${version}"` }) } });
  }

  postGeodataEntityReview<T = unknown>(entityId: string, body: unknown, version?: number): Promise<T> {
    return this.request<T>(`/v1/geodata/entities/${encodeURIComponent(entityId)}/reviews`, { method: 'POST', body, headers: { 'Idempotency-Key': crypto.randomUUID(), ...(version === undefined ? {} : { 'If-Match': `"${version}"` }) } });
  }

  postGeodataProposal<T = unknown>(body: unknown): Promise<T> {
    return this.request<T>('/v1/geodata/proposals', { method: 'POST', body, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }

  createGeodataEntityDeletionJob<T = unknown>(body: unknown): Promise<T> {
    return this.request<T>('/v1/geodata/entity-deletion-jobs', { method: 'POST', body, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }

  confirmGeodataEntityDeletionJob<T = unknown>(jobId: string, body: unknown): Promise<T> {
    return this.request<T>(`/v1/geodata/entity-deletion-jobs/${encodeURIComponent(jobId)}/confirm`, { method: 'POST', body, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }

  patchAward<T = unknown>(awardId: string, body: unknown): Promise<T> {
    return this.request<T>(`/v1/awards/${encodeURIComponent(awardId)}`, { method: 'PATCH', body, headers: { 'Idempotency-Key': crypto.randomUUID() } });
  }
}
