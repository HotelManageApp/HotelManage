import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KnowledgeManager } from "@/components/knowledge/KnowledgeManager";
import { HotelInfoForm } from "@/components/reception/HotelInfoForm";
import type { HotelInfo, KbEntry, Place } from "@/lib/knowledge/types";
import { envelope, json, mockBackend, renderWithAuth, session } from "../auth/helpers";

const RECEPTIONIST = {
  id: "r-1",
  email: "lt@h.test",
  full_name: "Le Tan",
  role: "RECEPTION" as const,
};
const signedIn = { "POST /api/v1/staff/auth/refresh": () => json(session("t", 900, RECEPTIONIST)) };

const BREAKFAST: KbEntry = {
  id: "e1",
  topic: "BREAKFAST",
  title_vi: "Giờ ăn sáng",
  title_en: "Breakfast hours",
  content_vi: "Bữa sáng 06:30–09:30 tại tầng 1.",
  content_en: "Breakfast 06:30–09:30 on the ground floor.",
  is_published: true,
  updated_at: "2026-11-20T01:00:00Z",
};
const MARKET: Place = {
  id: "p1",
  category: "ATTRACTION",
  name: "Chợ Bến Thành",
  description_vi: "Chợ truyền thống",
  description_en: "Traditional market",
  distance_km: 1.2,
  open_hours: "06:00–18:00",
  map_url: "https://maps.google.com/?q=Ben+Thanh",
  is_published: true,
  updated_at: "2026-11-20T01:00:00Z",
};

type Fetch = ReturnType<typeof mockBackend>;
const calls = (fetchMock: Fetch, method: string, path: string) =>
  fetchMock.mock.calls
    .filter(
      ([u, init]) => new URL(String(u)).pathname === path && (init?.method ?? "GET") === method,
    )
    .map(([u, init]) => ({
      url: new URL(String(u)),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    }));

function backend(routes: Record<string, () => Response> = {}) {
  return mockBackend({
    ...signedIn,
    "GET /api/v1/kb/entries": () => json([BREAKFAST]),
    "GET /api/v1/kb/places": () => json([MARKET]),
    ...routes,
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("KnowledgeManager — hotel information", () => {
  it("adds an entry only with both languages; copy from Vietnamese fills English", async () => {
    const fetchMock = backend({ "POST /api/v1/kb/entries": () => json(BREAKFAST, 201) });
    renderWithAuth(<KnowledgeManager />);

    expect(await screen.findByTestId("entry-e1")).toHaveTextContent("Giờ ăn sáng");
    const form = screen.getByRole("form", { name: "Thêm mục thông tin" });
    const submit = within(form).getByRole("button", { name: "Thêm mục thông tin" });
    await userEvent.selectOptions(within(form).getByLabelText("Chủ đề"), "WIFI");
    await userEvent.type(within(form).getByLabelText("Tiêu đề (tiếng Việt)"), " Wi-Fi miễn phí ");
    await userEvent.type(within(form).getByLabelText("Nội dung (tiếng Việt)"), "Mạng Hotel-Guest");
    expect(submit).toBeDisabled();

    await userEvent.click(within(form).getByRole("button", { name: "Sao chép từ tiếng Việt" }));
    expect(within(form).getByLabelText("Tiêu đề (tiếng Anh)")).toHaveValue(" Wi-Fi miễn phí ");
    await userEvent.click(submit);

    await waitFor(() =>
      expect(calls(fetchMock, "POST", "/api/v1/kb/entries")[0]?.body).toEqual({
        topic: "WIFI",
        title_vi: "Wi-Fi miễn phí",
        title_en: "Wi-Fi miễn phí",
        content_vi: "Mạng Hotel-Guest",
        content_en: "Mạng Hotel-Guest",
        is_published: true,
      }),
    );
    await waitFor(() =>
      expect(within(form).getByLabelText("Tiêu đề (tiếng Việt)")).toHaveValue(""),
    );
  });

  it("hides an entry with the publish switch, edits and deletes it", async () => {
    const fetchMock = backend({
      "PATCH /api/v1/kb/entries/e1": () => json(BREAKFAST),
      "DELETE /api/v1/kb/entries/e1": () => new Response(null, { status: 204 }),
    });
    renderWithAuth(<KnowledgeManager />);

    await userEvent.click(await screen.findByRole("switch", { name: "Xuất bản Giờ ăn sáng" }));
    await waitFor(() =>
      expect(calls(fetchMock, "PATCH", "/api/v1/kb/entries/e1")[0]?.body).toEqual({
        is_published: false,
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Sửa Giờ ăn sáng" }));
    const edit = screen.getByRole("form", { name: "Lưu" });
    const content = within(edit).getByLabelText("Nội dung (tiếng Việt)");
    await userEvent.clear(content);
    await userEvent.type(content, "Bữa sáng 07:00–10:00.");
    await userEvent.click(within(edit).getByRole("button", { name: "Lưu" }));
    await waitFor(() =>
      expect(calls(fetchMock, "PATCH", "/api/v1/kb/entries/e1")[1]?.body).toMatchObject({
        content_vi: "Bữa sáng 07:00–10:00.",
        title_en: "Breakfast hours",
      }),
    );

    await userEvent.click(await screen.findByRole("button", { name: "Xóa" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Xóa “Giờ ăn sáng”?");
    await userEvent.click(screen.getByRole("button", { name: "Xác nhận" }));
    await waitFor(() =>
      expect(calls(fetchMock, "DELETE", "/api/v1/kb/entries/e1")).toHaveLength(1),
    );
  });

  it("filters by topic and explains a refused save", async () => {
    const fetchMock = backend({
      "POST /api/v1/kb/entries": () => envelope(400, "VALIDATION_ERROR"),
    });
    renderWithAuth(<KnowledgeManager />);
    await screen.findByTestId("entry-e1");
    await userEvent.selectOptions(screen.getByLabelText("Lọc theo chủ đề"), "POLICIES");
    await waitFor(() =>
      expect(calls(fetchMock, "GET", "/api/v1/kb/entries").at(-1)?.url.search).toBe(
        "?topic=POLICIES",
      ),
    );

    const form = screen.getByRole("form", { name: "Thêm mục thông tin" });
    for (const label of [
      "Tiêu đề (tiếng Việt)",
      "Tiêu đề (tiếng Anh)",
      "Nội dung (tiếng Việt)",
      "Nội dung (tiếng Anh)",
    ]) {
      await userEvent.type(within(form).getByLabelText(label), "x");
    }
    await userEvent.click(within(form).getByRole("button", { name: "Thêm mục thông tin" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Thông tin chưa hợp lệ");
  });
});

describe("KnowledgeManager — nearby places", () => {
  it("refuses map links outside Google Maps and sends empty fields as null", async () => {
    const fetchMock = backend({ "POST /api/v1/kb/places": () => json(MARKET, 201) });
    renderWithAuth(<KnowledgeManager />);
    await userEvent.click(await screen.findByRole("tab", { name: "Địa điểm lân cận" }));
    expect(screen.getByTestId("place-p1")).toHaveTextContent("1.2 km");

    const form = screen.getByRole("form", { name: "Thêm địa điểm" });
    const submit = within(form).getByRole("button", { name: "Thêm địa điểm" });
    await userEvent.selectOptions(within(form).getByLabelText("Loại"), "FOOD_NEARBY");
    await userEvent.type(within(form).getByLabelText("Tên địa điểm"), "Phở Hòa");
    await userEvent.type(within(form).getByLabelText("Link bản đồ"), "https://evil.example.com/x");
    expect(within(form).getByText(/Chỉ nhận link https:\/\/maps.google.com/)).toBeInTheDocument();
    expect(submit).toBeDisabled();

    await userEvent.clear(within(form).getByLabelText("Link bản đồ"));
    await userEvent.type(within(form).getByLabelText("Khoảng cách (km)"), "0,6");
    await userEvent.click(submit);
    await waitFor(() =>
      expect(calls(fetchMock, "POST", "/api/v1/kb/places")[0]?.body).toEqual({
        category: "FOOD_NEARBY",
        name: "Phở Hòa",
        description_vi: null,
        description_en: null,
        distance_km: 0.6,
        open_hours: null,
        map_url: null,
        is_published: true,
      }),
    );
  });

  it("clears an optional field when editing and filters by category", async () => {
    const fetchMock = backend({ "PATCH /api/v1/kb/places/p1": () => json(MARKET) });
    renderWithAuth(<KnowledgeManager />);
    await userEvent.click(await screen.findByRole("tab", { name: "Địa điểm lân cận" }));
    await userEvent.click(screen.getByRole("button", { name: "Sửa Chợ Bến Thành" }));
    const edit = screen.getByRole("form", { name: "Lưu" });
    await userEvent.clear(within(edit).getByLabelText("Link bản đồ"));
    await userEvent.click(within(edit).getByRole("button", { name: "Lưu" }));
    await waitFor(() =>
      expect(calls(fetchMock, "PATCH", "/api/v1/kb/places/p1")[0]?.body).toMatchObject({
        map_url: null,
        distance_km: 1.2,
      }),
    );

    await userEvent.selectOptions(screen.getByLabelText("Lọc theo loại"), "HEALTH");
    await waitFor(() =>
      expect(calls(fetchMock, "GET", "/api/v1/kb/places").at(-1)?.url.search).toBe(
        "?category=HEALTH",
      ),
    );
  });
});

describe("Try a question", () => {
  it("shows what the bot would get, without calling the AI", async () => {
    const fetchMock = backend({
      "GET /api/v1/kb/search": () =>
        json({
          found: true,
          entries: [{ id: "e1", title: "Giờ ăn sáng", content: "Bữa sáng 06:30–09:30." }],
          places: [
            {
              name: "Phở Hòa",
              category: "FOOD_NEARBY",
              distance_km: 0.6,
              open_hours: null,
              note: "Quán lâu năm",
            },
          ],
        }),
    });
    renderWithAuth(<KnowledgeManager />);
    const box = await screen.findByRole("region", { name: "Thử hỏi" });
    await userEvent.type(within(box).getByLabelText("Câu hỏi của khách"), "Mấy giờ ăn sáng?");
    await userEvent.selectOptions(within(box).getByLabelText("Ngôn ngữ"), "en");
    await userEvent.click(within(box).getByRole("button", { name: "Thử" }));

    const result = await within(box).findByTestId("try-result");
    expect(result).toHaveTextContent("Giờ ăn sáng: Bữa sáng 06:30–09:30.");
    expect(result).toHaveTextContent("Phở Hòa · 0.6 km — Quán lâu năm");
    const params = calls(fetchMock, "GET", "/api/v1/kb/search")[0]?.url.searchParams;
    expect(Object.fromEntries(params ?? [])).toEqual({
      topic: "OTHER",
      q: "Mấy giờ ăn sáng?",
      lang: "en",
    });
  });

  it("says what the bot will answer when nothing is found", async () => {
    backend({
      "GET /api/v1/kb/search": () => json({ found: false, entries: [], places: [] }),
    });
    renderWithAuth(<KnowledgeManager />);
    const box = await screen.findByRole("region", { name: "Thử hỏi" });
    await userEvent.type(within(box).getByLabelText("Câu hỏi của khách"), "Có sân golf không?");
    await userEvent.click(within(box).getByRole("button", { name: "Thử" }));
    expect(await within(box).findByTestId("try-result")).toHaveTextContent(
      "chatbot sẽ trả lời “chưa có thông tin”",
    );
  });
});

describe("HotelInfoForm", () => {
  const INFO: HotelInfo = {
    hotel_name: "Hotel",
    reception_phone: "",
    default_lang: "vi",
    chat_enabled: true,
  };

  it("turns the chatbot off and saves name, phone and language", async () => {
    const fetchMock = mockBackend({
      ...signedIn,
      "GET /api/v1/settings/hotel": () => json(INFO),
      "PATCH /api/v1/settings/hotel": (_url, init) =>
        json({ ...INFO, ...JSON.parse(String(init.body)) }),
    });
    renderWithAuth(<HotelInfoForm />);

    const chat = await screen.findByRole("switch", { name: "Chatbot Concierge" });
    await userEvent.click(chat);
    expect(await screen.findByRole("status")).toHaveTextContent("Đã tắt chatbot");
    expect(screen.getByText("Đang tắt — app báo khách liên hệ Lễ tân")).toBeInTheDocument();

    const name = screen.getByLabelText("Tên khách sạn");
    await userEvent.clear(name);
    await userEvent.type(name, "Khách sạn Hoa Sen");
    await userEvent.type(screen.getByLabelText("SĐT Lễ tân"), "028 3822 1234");
    await userEvent.selectOptions(screen.getByLabelText("Ngôn ngữ mặc định"), "en");
    await userEvent.click(screen.getByRole("button", { name: "Lưu thông tin" }));

    await waitFor(() =>
      expect(calls(fetchMock, "PATCH", "/api/v1/settings/hotel").map((c) => c.body)).toEqual([
        { chat_enabled: false },
        { hotel_name: "Khách sạn Hoa Sen", reception_phone: "028 3822 1234", default_lang: "en" },
      ]),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Đã lưu thông tin khách sạn");
  });

  it("blocks an invalid phone and an empty name", async () => {
    mockBackend({ ...signedIn, "GET /api/v1/settings/hotel": () => json(INFO) });
    renderWithAuth(<HotelInfoForm />);
    await userEvent.type(await screen.findByLabelText("SĐT Lễ tân"), "gọi tôi");
    expect(screen.getByText("Chỉ gồm số, khoảng trắng và + ( ) . -")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lưu thông tin" })).toBeDisabled();
    await userEvent.clear(screen.getByLabelText("SĐT Lễ tân"));
    await userEvent.clear(screen.getByLabelText("Tên khách sạn"));
    expect(screen.getByRole("button", { name: "Lưu thông tin" })).toBeDisabled();
  });
});
