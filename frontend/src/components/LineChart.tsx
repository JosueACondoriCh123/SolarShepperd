import {
  CategoryScale,
  Chart as ChartJS,
  Filler,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  TimeScale,
  Title,
  Tooltip,
  type ChartOptions,
} from "chart.js";
import { memo, useMemo } from "react";
import { Line } from "react-chartjs-2";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  TimeScale,
  Title,
  Tooltip,
  Legend,
  Filler
);

interface Series {
  label: string;
  color: string;
  values: { x: string | number; y: number }[];
}

export const LineChart = memo(function LineChart({
  series,
  unit,
  height = 250,
}: {
  series: Series[];
  unit?: string;
  height?: number;
}) {
  const data = useMemo(
    () => ({
      datasets: series.map((item) => ({
        label: item.label,
        data: item.values,
        borderColor: item.color,
        backgroundColor: `${item.color}18`,
        pointRadius: 2,
        pointHoverRadius: 5,
        pointBorderWidth: 2,
        pointBackgroundColor: "#fff8e8",
        borderWidth: 3,
        tension: 0,
        fill: true,
      })),
    }),
    [series]
  );

  const options: ChartOptions<"line"> = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          labels: {
            color: "#2a241c",
            font: { family: "Cascadia Mono, Courier New, monospace", weight: 700 },
            usePointStyle: true,
            boxWidth: 8,
          },
        },
        tooltip: {
          backgroundColor: "#fff8e8",
          bodyColor: "#171717",
          titleColor: "#171717",
          borderColor: "#171717",
          borderWidth: 2,
          cornerRadius: 0,
        },
      },
      scales: {
        x: {
          type: "linear",
          ticks: {
            color: "#5b5144",
            font: { family: "Cascadia Mono, Courier New, monospace", weight: 600 },
            callback: (value) =>
              new Date(Number(value)).toLocaleDateString(undefined, {
                month: "short",
                day: "numeric",
              }),
            maxTicksLimit: 6,
          },
          grid: { color: "rgba(23,23,23,0.11)" },
        },
        y: {
          ticks: {
            color: "#5b5144",
            font: { family: "Cascadia Mono, Courier New, monospace", weight: 600 },
            callback: (value) => `${value}${unit ? ` ${unit}` : ""}`,
          },
          grid: { color: "rgba(23,23,23,0.11)" },
        },
      },
    }),
    [unit]
  );

  return (
    <div style={{ height }}>
      <Line data={data} options={options} />
    </div>
  );
});
