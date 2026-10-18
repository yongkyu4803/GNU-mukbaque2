import { test, expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

const sequence = "RMKQLEDKVEELLSKNYHLENEVARLKKLVGER";
async function open(page: Page) {
  await page.goto("/");
  await expect(
    page.getByText("연구 워커 연결됨", { exact: true }),
  ).toBeVisible();
}
async function selectExample(page: Page) {
  await page.getByRole("button", { name: /GCN4 예제/ }).click();
  await page.getByRole("button", { name: "표적 등록 · 분석" }).click();
  await expect(page.locator("#saved-target")).not.toHaveValue("");
}

test("empty state, fonts, responsive layout and no client exceptions", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await open(page);
  await expect(
    page.getByRole("heading", { name: "류신 지퍼 파트너 탐색" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "라이브러리 스크리닝", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByText("다음 연결을 발견할 준비가 되었습니다"),
  ).toBeVisible();
  await page.evaluate(() => document.fonts.ready);
  const fonts = await page.evaluate(() => ({
    heading: document.fonts.check("700 24px KIMMBold"),
    body: document.fonts.check("400 14px Pretendard"),
  }));
  expect(fonts).toEqual({ heading: true, body: true });
  await page.screenshot({
    path: "test-results/empty-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.getByRole("button", { name: "탐색 메뉴" }).click();
  await expect(
    page.getByRole("link", { name: "모델 보정", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "모델 보정", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "실험 데이터로 점수 보정" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("register example, real screening, candidate selection and CSV download", async ({
  page,
}) => {
  await open(page);
  await selectExample(page);
  await expect(page.locator("#target-detail")).toContainText("33 aa");
  await page
    .getByRole("button", { name: "라이브러리 스크리닝", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "라이브러리 스크리닝 결과" }),
  ).toBeVisible();
  await expect(page.locator(".candidate-table tbody tr")).toHaveCount(5);
  await expect(page.locator(".score-chart")).toBeVisible();
  await page.getByRole("button", { name: /c-Fos-LZ/ }).click();
  await expect(page.locator("#candidate-detail")).toContainText("c-Fos-LZ");
  await page
    .getByRole("checkbox", { name: "후보 전체 선택", exact: true })
    .uncheck();
  await page
    .getByRole("checkbox", { name: "c-Fos-LZ 선택", exact: true })
    .check();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "CSV 1", exact: true }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("lz-candidates.csv");
  await page.screenshot({
    path: "test-results/screening-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "test-results/screening-mobile.png",
    fullPage: true,
  });
});

test("design completes, files download and history survives reload", async ({
  page,
}) => {
  await open(page);
  await selectExample(page);
  await page.locator("#restarts").fill("1");
  await page.locator("#steps").fill("100");
  await page.locator("#seed").fill("17");
  await page.getByRole("button", { name: "설계 실행", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "파트너 설계 결과", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".run-strip .badge")).toHaveText("완료");
  await page.locator(".download-menu summary").click();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: /complexes.fasta/ }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("complexes.fasta");
  await page.getByRole("link", { name: "실행 이력", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "연구 실행 이력" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "결과 보기" }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "결과 보기" }).first().click();
  await expect(
    page.getByRole("heading", { name: "파트너 설계 결과" }),
  ).toBeVisible();
});

test("orthogonal final re-evaluation and interaction matrix use real worker result", async ({
  page,
}) => {
  await open(page);
  await page.getByRole("radio", { name: /직교 세트 설계/ }).check();
  await page.locator("#fixed-target").uncheck();
  await page.locator("#restarts").fill("1");
  await page.locator("#steps").fill("2000");
  await page.locator("#seed").fill("20");
  await page.getByRole("button", { name: "설계 실행", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "직교 세트 결과", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "설계 마진 미충족", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".matrix-table tbody tr")).toHaveCount(4);
  await expect(page.locator(".run-strip .badge")).toHaveText("완료");
  await page.screenshot({
    path: "test-results/orthogonal-desktop.png",
    fullPage: true,
  });
});

test("FASTA library import is available to the workspace", async ({ page }) => {
  await open(page);
  await page
    .getByRole("link", { name: "서열 라이브러리", exact: true })
    .click();
  await page
    .locator("#library-file")
    .setInputFiles({
      name: "browser-test-library.fasta",
      mimeType: "text/plain",
      buffer: Buffer.from(`>Browser-test\n${sequence}\n`),
    });
  await expect(page.locator(".catalog-item.chosen")).toContainText(
    "browser-test-library.fasta",
  );
  await expect(page.locator("table")).toContainText("Browser-test");
  await page.getByRole("link", { name: "파트너 탐색", exact: true }).click();
  await expect(page.locator("#library-select option:checked")).toContainText(
    "browser-test-library.fasta",
  );
});

test("CSV calibration upload yields a selectable persisted model", async ({
  page,
}) => {
  const csv = execFileSync(
    resolve("../.venv/bin/python"),
    [
      "-c",
      "from tests.test_server import calibration_csv; print(calibration_csv())",
    ],
    { cwd: resolve("..") },
  );
  await open(page);
  await page.getByRole("link", { name: "모델 보정", exact: true }).click();
  await page
    .locator("#calibration-file")
    .setInputFiles({ name: "test-tm.csv", mimeType: "text/csv", buffer: csv });
  await page.getByRole("button", { name: "보정 실행", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "연구 실행 이력" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr").first()).toContainText("완료");
  await page.getByRole("link", { name: "모델 보정", exact: true }).click();
  await expect(page.locator("table")).toContainText("Calibration run_");
  await expect(page.locator("table")).toContainText("학습 데이터만 평가");
});

test("invalid sequence shows a real API validation error without losing the form", async ({
  page,
}) => {
  await open(page);
  await page.locator("#target-name").fill("Invalid example");
  await page.locator("#target-sequence").fill("XXXXXXX");
  await page.getByRole("button", { name: "표적 등록 · 분석" }).click();
  await expect(page.locator(".toast-error")).toContainText("unknown residue");
  await expect(page.locator("#target-sequence")).toHaveValue("XXXXXXX");
});

test("PDB upload measures geometry and preserves the chosen chain", async ({
  page,
}) => {
  const pdb = execFileSync(
    resolve("../.venv/bin/python"),
    [
      "-c",
      `from tests.make_structure import build_dimer; print(build_dimer('${sequence}',start_position='g'))`,
    ],
    { cwd: resolve("..") },
  );
  await open(page);
  await page
    .getByRole("tab", { name: "PDB / FASTA 가져오기", exact: true })
    .click();
  await page
    .locator("#target-file")
    .setInputFiles({
      name: "Crick-geometry-DEMO.pdb",
      mimeType: "text/plain",
      buffer: pdb,
    });
  await page.locator("#target-chain").fill("B");
  await page
    .getByRole("button", { name: "표적 등록 · 분석", exact: true })
    .click();
  await expect(page.locator(".research-note")).toContainText("구조 좌표 측정");
  await expect(page.locator("#target-detail")).toContainText("parallel");
});

test("active design can be cancelled and retried through the client", async ({
  page,
}) => {
  await open(page);
  await page.locator("#restarts").fill("16");
  await page.locator("#steps").fill("20000");
  await page.getByRole("button", { name: "설계 실행", exact: true }).click();
  await page
    .locator(".run-strip")
    .getByRole("button", { name: "취소", exact: true })
    .click();
  await expect(page.locator(".run-strip .badge")).toHaveText("취소됨");
  await page
    .locator(".run-strip")
    .getByRole("button", { name: "다시 실행", exact: true })
    .click();
  await expect(page.locator(".run-strip .badge")).toHaveText(/대기 중|계산 중/);
  await page
    .locator(".run-strip")
    .getByRole("button", { name: "취소", exact: true })
    .click();
  await expect(page.locator(".run-strip .badge")).toHaveText("취소됨");
});
