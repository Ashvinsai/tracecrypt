import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useMemo, useState, type ReactNode } from "react";

export interface DataTableProps<T> {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  /** Controlled global filter; a caller renders the search input. */
  filter?: string;
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
  selectedRowId?: string;
  rowId?: (row: T) => string;
  maxHeight?: string;
  dense?: boolean;
}

export function DataTable<T>({
  columns,
  data,
  filter = "",
  empty,
  onRowClick,
  selectedRowId,
  rowId,
  maxHeight = "70vh",
}: DataTableProps<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const memoColumns = useMemo(() => columns, [columns]);

  // TanStack Table returns a stable table instance whose row-model accessors are
  // intentionally re-created per render; the React Compiler cannot memoize this
  // hook, which is expected for this library and not a defect here.
  // eslint-disable-next-line react/incompatible-library
  const table = useReactTable({
    data,
    columns: memoColumns,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    columnResizeMode: "onChange",
    enableColumnResizing: true,
  });

  if (data.length === 0 && empty) {
    return <>{empty}</>;
  }

  return (
    <div className="table-wrap">
      <div className="table-scroll" style={{ maxHeight }}>
        <table className="data" style={{ width: table.getCenterTotalSize() }}>
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    style={{ width: header.getSize(), position: "relative" }}
                    aria-sort={
                      header.column.getIsSorted() === "asc"
                        ? "ascending"
                        : header.column.getIsSorted() === "desc"
                          ? "descending"
                          : undefined
                    }
                  >
                    {header.isPlaceholder ? null : (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        style={{
                          border: 0,
                          background: "transparent",
                          color: "inherit",
                          font: "inherit",
                          padding: 0,
                          cursor: header.column.getCanSort() ? "pointer" : "default",
                          display: "inline-flex",
                          gap: 4,
                        }}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {header.column.getIsSorted() === "asc"
                          ? " ▲"
                          : header.column.getIsSorted() === "desc"
                            ? " ▼"
                            : ""}
                      </button>
                    )}
                    {header.column.getCanResize() ? (
                      <span
                        onMouseDown={header.getResizeHandler()}
                        onTouchStart={header.getResizeHandler()}
                        style={{
                          position: "absolute",
                          right: 0,
                          top: 0,
                          height: "100%",
                          width: 5,
                          cursor: "col-resize",
                          userSelect: "none",
                          touchAction: "none",
                        }}
                        aria-hidden="true"
                      />
                    ) : null}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => {
              const id = rowId ? rowId(row.original) : row.id;
              return (
                <tr
                  key={id}
                  className={`${onRowClick ? "selectable" : ""}${selectedRowId === id ? " selected" : ""}`}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} style={{ width: cell.column.getSize() }}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
