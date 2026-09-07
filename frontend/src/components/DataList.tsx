import { useApi } from "../lib/useApi";
import { ComingSoon, EmptyState, ErrorState, Loading } from "./States";

export interface Column<T> {
  header: string;
  render: (row: T) => React.ReactNode;
}

// Generic list screen: fetches { items, count } from an endpoint and renders a
// card + table. Honors 501 (ComingSoon), loading, empty, and error states.
export default function DataList<T extends { id?: string }>(props: {
  title: string;
  subtitle?: string;
  path: string;
  feature: string;
  columns: Column<T>[];
  emptyMessage?: string;
  headerAction?: React.ReactNode;
}) {
  const { data, loading, error, comingSoon } = useApi<{ items: T[]; count: number }>(props.path);

  return (
    <>
      <div className="page-head flex between">
        <div><h1>{props.title}</h1>{props.subtitle && <p>{props.subtitle}</p>}</div>
        {props.headerAction}
      </div>

      {loading && <Loading />}
      {comingSoon && <ComingSoon feature={props.feature} />}
      {error && <ErrorState message={error} />}
      {!loading && !error && !comingSoon && data && data.items.length === 0 && (
        <EmptyState message={props.emptyMessage ?? "Nothing here yet."} />
      )}
      {!loading && !error && !comingSoon && data && data.items.length > 0 && (
        <div className="card">
          <div className="card-head"><h3>{props.title}</h3><span className="faint small">{data.count} items</span></div>
          <table className="tbl" data-testid={`list-${props.feature.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
            <thead><tr>{props.columns.map((c) => <th key={c.header}>{c.header}</th>)}</tr></thead>
            <tbody>
              {data.items.map((row, i) => (
                <tr key={row.id ?? i}>{props.columns.map((c) => <td key={c.header}>{c.render(row)}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
