import Link from "next/link";
import { deleteAsset, setAssetStatus } from "@/app/actions";
import { ConfirmButton } from "@/components/ConfirmButton";
import { CopyButton } from "@/components/CopyButton";
import { listHref } from "@/components/ListControls";
import { Badge, Card, Empty } from "@/components/ui";
import { api } from "@/lib/backend";
import { date, fileSize } from "@/lib/format";
import type { Asset, AssetPage } from "@/lib/types";
import { EditAsset, NewAsset } from "./AssetForms";

export const metadata = { title: "Assets" };

const PATH = "/dashboard/assets";
const TABS: [string, string, keyof AssetPage["counts"]][] = [["", "All", "all"], ["published", "Published", "published"], ["draft", "Drafts", "draft"]];
const TYPES: [string, string][] = [["", "All types"], ["image", "Images"], ["file", "Files"], ["link", "Links"], ["text", "Copy"]];
const SORTS: [string, string][] = [["newest", "Newest first"], ["oldest", "Oldest first"], ["name", "Name"]];
const TYPE_LABEL = { image: "image", file: "file", link: "link", text: "copy" };

function Preview({ a }: { a: Asset }) {
  if (a.type === "image" && a.file) {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={a.file.url} alt={a.name} className="h-28 w-full rounded-lg border border-line bg-sunk/50 object-contain" />;
  }
  if (a.type === "text") return <p className="line-clamp-4 h-28 overflow-hidden whitespace-pre-line rounded-lg border border-line bg-sunk/50 p-3 text-xs">{a.text}</p>;
  if (a.type === "link") return <p className="flex h-28 items-center break-all rounded-lg border border-line bg-sunk/50 p-3 font-mono text-xs">{a.url}</p>;
  return (
    <a href={a.file?.url} className="flex h-28 flex-col items-center justify-center rounded-lg border border-line bg-sunk/50 p-3 text-center text-xs hover:bg-sunk">
      <span className="font-mono">{a.file?.name}</span>
      {a.file && <span className="mt-1 text-muted">{fileSize(a.file.size)}</span>}
    </a>
  );
}

export default async function AssetsPage({ searchParams }: { searchParams: Promise<{ status?: string; type?: string; q?: string; sort?: string }> }) {
  const sp = await searchParams;
  const status = TABS.some(([v]) => v && v === sp.status) ? sp.status : undefined;
  const type = TYPES.some(([v]) => v && v === sp.type) ? sp.type : undefined;
  const sort = SORTS.some(([v]) => v === sp.sort) ? sp.sort! : "newest";
  const q = sp.q?.trim() || undefined;
  const qs = new URLSearchParams({ sort });
  if (status) qs.set("status", status);
  if (type) qs.set("type", type);
  if (q) qs.set("q", q);
  const res = await api<AssetPage>(`/merchant/assets?${qs}`);
  const filtered = Boolean(q || type);

  return (
    <div className="space-y-6">
      <h1 className="page-title">Assets</h1>
      <p className="text-sm text-muted">
        Logos, banners, copy and links for your affiliates to promote you with. Published assets show in every affiliate&apos;s portal, with links and copy already carrying their own link. Drafts are only visible to your team.
      </p>

      <Card title="Add an asset">
        <NewAsset />
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1 text-sm">
          {TABS.map(([value, label, key]) => (
            <Link key={label} href={listHref(PATH, { status: value, type, q, sort: sort === "newest" ? undefined : sort })} className={`btn ${(status ?? "") === value ? "btn-primary" : "btn-secondary"}`}>
              {label} <span className="opacity-70">{res.counts[key]}</span>
            </Link>
          ))}
        </div>
        <form action={PATH} className="flex flex-wrap gap-2" role="search">
          {status && <input type="hidden" name="status" value={status} />}
          <input className="input w-44" type="search" name="q" defaultValue={q ?? ""} placeholder="Search by name" aria-label="Search by name" />
          <select className="input w-auto" name="type" defaultValue={type ?? ""} aria-label="Type">
            {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <select className="input w-auto" name="sort" defaultValue={sort} aria-label="Sort">
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <button className="btn btn-secondary">Apply</button>
          {(filtered || sort !== "newest") && <Link className="btn btn-secondary" href={listHref(PATH, { status })}>Clear</Link>}
        </form>
      </div>

      {res.items.length === 0 ? (
        <Card><Empty>{filtered ? "No assets match." : res.counts.all === 0 ? "No assets yet. Add your logo, a banner or a ready-to-post blurb above." : "Nothing here."}</Empty></Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {res.items.map((a) => (
            <div key={a.id} className="card flex flex-col gap-3 p-4">
              <Preview a={a} />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="truncate font-medium">{a.name}</p>
                  <Badge tone={a.status === "published" ? "green" : "gray"}>{a.status === "published" ? "published" : "draft"}</Badge>
                </div>
                <p className="text-xs text-muted">{TYPE_LABEL[a.type]} · added {date(a.created_at)}</p>
                {a.description && <p className="mt-1 text-sm text-muted">{a.description}</p>}
              </div>
              <div className="mt-auto flex flex-wrap items-center gap-2">
                <form action={setAssetStatus.bind(null, a.id, a.status === "published" ? "draft" : "published")}>
                  <button className={`btn ${a.status === "published" ? "btn-secondary" : "btn-primary"}`}>{a.status === "published" ? "Unpublish" : "Publish"}</button>
                </form>
                {a.file && <CopyButton text={a.file.url} label="Copy URL" />}
                <ConfirmButton action={deleteAsset.bind(null, a.id)} confirmText={`Delete “${a.name}”? Affiliates stop seeing it${a.file ? " and its file stops downloading" : ""}.`} className="btn btn-secondary text-red-700">Delete</ConfirmButton>
              </div>
              <EditAsset a={a} />
            </div>
          ))}
        </div>
      )}
      <p className="text-xs text-muted">{fileSize(res.storage.used)} of {fileSize(res.storage.limit)} file storage used.</p>
    </div>
  );
}
