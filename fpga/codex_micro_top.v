module codex_micro_top (
    input        clk_50M,
    input        key0_n,
    input        key1_n,
    input        key2_n,
    input        key3_n,
    input        key4_n,
    input        send_sw,
    input        speak_sw,
    input        uart_rx,
    output       uart_tx,
    output [7:0] led,
    output [3:0] seg_sel,
    output [7:0] seg_led,
    output       buzzer
);
    parameter CLK_HZ = 50_000_000;

    // The reconfiguration key is a dedicated board function. The user keys
    // remain available to the controller, so startup reset is internal.
    reg [22:0] power_count;
    initial power_count = 23'd0;

    always @(posedge clk_50M) begin
        if (!(&power_count)) begin
            power_count <= power_count + 1'b1;
        end
    end

    wire rst_n = &power_count;

    wire key0_down;
    wire key0_up;
    wire key0_long;
    wire key1_down;
    wire key1_up;
    wire key1_long;
    wire key2_down;
    wire key2_up;
    wire key2_long;
    wire key3_down;
    wire key3_up;
    wire key3_long;
    wire key4_down;
    wire key4_up;
    wire key4_long;
    wire send_edge;

    key_event #(.CLK_HZ(CLK_HZ), .ACTIVE_LOW(1'b1)) u_key0 (
        .clk(clk_50M), .rst_n(rst_n), .raw_in(key0_n),
        .down_pulse(key0_down), .up_pulse(key0_up), .long_pulse(key0_long)
    );
    key_event #(.CLK_HZ(CLK_HZ), .ACTIVE_LOW(1'b1)) u_key1 (
        .clk(clk_50M), .rst_n(rst_n), .raw_in(key1_n),
        .down_pulse(key1_down), .up_pulse(key1_up), .long_pulse(key1_long)
    );
    key_event #(.CLK_HZ(CLK_HZ), .ACTIVE_LOW(1'b1)) u_key2 (
        .clk(clk_50M), .rst_n(rst_n), .raw_in(key2_n),
        .down_pulse(key2_down), .up_pulse(key2_up), .long_pulse(key2_long)
    );
    key_event #(.CLK_HZ(CLK_HZ), .ACTIVE_LOW(1'b1)) u_key3 (
        .clk(clk_50M), .rst_n(rst_n), .raw_in(key3_n),
        .down_pulse(key3_down), .up_pulse(key3_up), .long_pulse(key3_long)
    );
    key_event #(.CLK_HZ(CLK_HZ), .ACTIVE_LOW(1'b1)) u_key4 (
        .clk(clk_50M), .rst_n(rst_n), .raw_in(key4_n),
        .down_pulse(key4_down), .up_pulse(key4_up), .long_pulse(key4_long)
    );
    key_event #(.CLK_HZ(CLK_HZ), .ACTIVE_LOW(1'b0)) u_send_sw (
        .clk(clk_50M), .rst_n(rst_n), .raw_in(send_sw),
        .down_pulse(send_edge), .up_pulse(), .long_pulse()
    );

    reg [2:0] speak_sw_sync;
    always @(posedge clk_50M) begin
        if (!rst_n) speak_sw_sync <= 3'b000;
        else speak_sw_sync <= {speak_sw_sync[1:0], speak_sw};
    end
    wire speak_enabled = speak_sw_sync[2];

    reg        event_valid;
    reg [7:0]  event_code;
    reg [7:0]  event_id;
    wire       tx_frame_busy;

    // Human input is bursty compared with the UART frame time. Queue events
    // so a key release or a short press cannot be lost while another frame is
    // being transmitted.
    reg [7:0] event_code_fifo [0:7];
    reg [7:0] event_id_fifo [0:7];
    reg [2:0] event_wr_ptr;
    reg [2:0] event_rd_ptr;
    reg [3:0] event_count;
    reg       source_event_valid;
    reg [7:0] source_event_code;
    reg [7:0] source_event_id;
    wire event_push = source_event_valid && (event_count < 8);
    wire event_pop = !tx_frame_busy && (event_count != 0);

    always @(*) begin
        source_event_valid = 1'b1;
        source_event_code = 8'h00;
        source_event_id = 8'h00;
        if (key0_down) begin source_event_code = 8'h01; source_event_id = 8'd0; end
        else if (key1_down) begin source_event_code = 8'h01; source_event_id = 8'd1; end
        else if (key2_down) begin source_event_code = 8'h01; source_event_id = 8'd2; end
        else if (key3_down) begin source_event_code = 8'h01; source_event_id = 8'd3; end
        else if (key4_down) begin source_event_code = 8'h01; source_event_id = 8'd4; end
        else if (key0_up) begin source_event_code = 8'h02; source_event_id = 8'd0; end
        else if (key1_up) begin source_event_code = 8'h02; source_event_id = 8'd1; end
        else if (key2_up) begin source_event_code = 8'h02; source_event_id = 8'd2; end
        else if (key3_up) begin source_event_code = 8'h02; source_event_id = 8'd3; end
        else if (key4_up) begin source_event_code = 8'h02; source_event_id = 8'd4; end
        else if (key0_long) begin source_event_code = speak_enabled ? 8'h11 : 8'h03; source_event_id = 8'd0; end
        else if (key1_long) begin source_event_code = speak_enabled ? 8'h11 : 8'h03; source_event_id = 8'd1; end
        else if (key2_long) begin source_event_code = speak_enabled ? 8'h11 : 8'h03; source_event_id = 8'd2; end
        else if (key3_long) begin source_event_code = speak_enabled ? 8'h11 : 8'h03; source_event_id = 8'd3; end
        else if (key4_long) begin source_event_code = 8'h03; source_event_id = 8'd4; end
        else if (send_edge) begin source_event_code = 8'h10; source_event_id = 8'hff; end
        else source_event_valid = 1'b0;
    end

    always @(posedge clk_50M) begin
        if (!rst_n) begin
            event_valid <= 1'b0;
            event_code <= 8'd0;
            event_id <= 8'd0;
            event_wr_ptr <= 3'd0;
            event_rd_ptr <= 3'd0;
            event_count <= 4'd0;
        end else begin
            event_valid <= 1'b0;
            if (event_push) begin
                event_code_fifo[event_wr_ptr] <= source_event_code;
                event_id_fifo[event_wr_ptr] <= source_event_id;
                event_wr_ptr <= event_wr_ptr + 1'b1;
            end
            if (event_pop) begin
                event_code <= event_code_fifo[event_rd_ptr];
                event_id <= event_id_fifo[event_rd_ptr];
                event_valid <= 1'b1;
                event_rd_ptr <= event_rd_ptr + 1'b1;
            end
            case ({event_push, event_pop})
                2'b10: event_count <= event_count + 1'b1;
                2'b01: event_count <= event_count - 1'b1;
                default: event_count <= event_count;
            endcase
        end
    end

    wire [7:0] rx_data;
    wire       rx_valid;
    uart_rx_byte #(.CLK_HZ(CLK_HZ), .BAUD(115200)) u_uart_rx (
        .clk(clk_50M), .rst_n(rst_n), .rx(uart_rx),
        .data(rx_data), .valid(rx_valid)
    );

    reg [7:0] status0;
    reg [7:0] status1;
    reg [7:0] status2;
    reg [7:0] status3;
    reg [7:0] led_on;
    reg [1:0] selected_slot;
    reg       operation_mode;
    reg [31:0] beep_ticks;
    reg [31:0] beep_phase;
    reg        buzzer_level;

    reg [2:0]  rx_state;
    reg [7:0]  rx_type;
    reg [7:0]  rx_len;
    reg [7:0]  rx_p0;
    reg [7:0]  rx_p1;
    reg [7:0]  rx_index;

    always @(posedge clk_50M) begin
        if (!rst_n) begin
            status0 <= 8'd0;
            status1 <= 8'd0;
            status2 <= 8'd0;
            status3 <= 8'd0;
            led_on <= 8'd0;
            selected_slot <= 2'd0;
            operation_mode <= 1'b0;
            rx_state <= 3'd0;
            rx_type <= 8'd0;
            rx_len <= 8'd0;
            rx_p0 <= 8'd0;
            rx_p1 <= 8'd0;
            rx_index <= 8'd0;
            beep_ticks <= 32'd0;
            beep_phase <= 32'd0;
            buzzer_level <= 1'b0;
        end else begin
            if (beep_ticks != 0) begin
                beep_ticks <= beep_ticks - 1'b1;
                if (beep_phase == (CLK_HZ / 4000) - 1) begin
                    beep_phase <= 32'd0;
                    buzzer_level <= ~buzzer_level;
                end else begin
                    beep_phase <= beep_phase + 1'b1;
                end
            end else begin
                buzzer_level <= 1'b0;
                beep_phase <= 32'd0;
            end

            if (rx_valid) begin
                case (rx_state)
                    3'd0: begin
                        if (rx_data == 8'haa) rx_state <= 3'd1;
                    end
                    3'd1: begin
                        if (rx_data == 8'h55) rx_state <= 3'd2;
                        else rx_state <= 3'd0;
                    end
                    3'd2: begin rx_type <= rx_data; rx_state <= 3'd3; end
                    3'd3: begin
                        rx_len <= rx_data;
                        rx_index <= 8'd0;
                        rx_p0 <= 8'd0;
                        rx_p1 <= 8'd0;
                        if (rx_data == 0 || rx_data > 2) rx_state <= 3'd0;
                        else rx_state <= 3'd4;
                    end
                    3'd4: begin
                        if (rx_index == 0) rx_p0 <= rx_data;
                        else rx_p1 <= rx_data;
                        rx_index <= rx_index + 1'b1;
                        if (rx_index + 1 >= rx_len) rx_state <= 3'd5;
                    end
                    3'd5: begin
                        rx_state <= 3'd0;
                        if (rx_data == (rx_type ^ rx_len ^ rx_p0 ^ rx_p1)) begin
                            case (rx_type)
                                8'h20: begin
                                    case (rx_p0)
                                        8'd0: status0 <= rx_p1;
                                        8'd1: status1 <= rx_p1;
                                        8'd2: status2 <= rx_p1;
                                        8'd3: status3 <= rx_p1;
                                        default: begin end
                                    endcase
                                end
                                8'h21: begin beep_ticks <= {16'd0, rx_p0, rx_p1} * (CLK_HZ / 1000); end
                                8'h22: begin operation_mode <= rx_p0[0]; end
                                8'h23: begin selected_slot <= rx_p0[1:0]; end
                                8'h24: begin led_on <= rx_p0; end
                                8'h25: begin status0 <= 0; status1 <= 0; status2 <= 0; status3 <= 0; end
                                default: begin end
                            endcase
                        end
                    end
                    default: rx_state <= 3'd0;
                endcase
            end
        end
    end

    assign buzzer = buzzer_level;
    assign led = ~led_on;

    frame_tx #(.CLK_HZ(CLK_HZ), .BAUD(115200)) u_frame_tx (
        .clk(clk_50M), .rst_n(rst_n),
        .event_valid(event_valid), .event_code(event_code), .event_id(event_id),
        .tx(uart_tx), .busy(tx_frame_busy)
    );

    seven_seg_status #(.CLK_HZ(CLK_HZ)) u_display (
        .clk(clk_50M), .rst_n(rst_n),
        .status0(status0), .status1(status1), .status2(status2), .status3(status3),
        .selected_slot(selected_slot), .operation_mode(operation_mode),
        .seg_sel(seg_sel), .seg_led(seg_led)
    );
endmodule

module key_event #(
    parameter CLK_HZ = 50_000_000,
    parameter ACTIVE_LOW = 1'b1
) (
    input  clk,
    input  rst_n,
    input  raw_in,
    output reg down_pulse,
    output reg up_pulse,
    output reg long_pulse
);
    localparam integer DEBOUNCE_TICKS = CLK_HZ / 50;
    localparam integer LONG_TICKS = CLK_HZ * 7 / 10;
    reg [2:0] sync_ff;
    reg stable_pressed;
    reg [31:0] debounce_count;
    reg [31:0] hold_count;
    reg long_sent;
    wire pressed = ACTIVE_LOW ? ~sync_ff[2] : sync_ff[2];

    always @(posedge clk) begin
        if (!rst_n) begin
            sync_ff <= ACTIVE_LOW ? 3'b111 : 3'b000;
            stable_pressed <= 1'b0;
            debounce_count <= 0;
            hold_count <= 0;
            long_sent <= 1'b0;
            down_pulse <= 1'b0;
            up_pulse <= 1'b0;
            long_pulse <= 1'b0;
        end else begin
            sync_ff <= {sync_ff[1:0], raw_in};
            down_pulse <= 1'b0;
            up_pulse <= 1'b0;
            long_pulse <= 1'b0;

            if (pressed != stable_pressed) begin
                if (debounce_count < DEBOUNCE_TICKS - 1) begin
                    debounce_count <= debounce_count + 1'b1;
                end else begin
                    debounce_count <= 0;
                    stable_pressed <= pressed;
                    hold_count <= 0;
                    long_sent <= 1'b0;
                    if (pressed) down_pulse <= 1'b1;
                    else up_pulse <= 1'b1;
                end
            end else begin
                debounce_count <= 0;
                if (stable_pressed) begin
                    if (hold_count < LONG_TICKS) hold_count <= hold_count + 1'b1;
                    if (!long_sent && hold_count >= LONG_TICKS - 1) begin
                        long_sent <= 1'b1;
                        long_pulse <= 1'b1;
                    end
                end
            end
        end
    end
endmodule

module uart_rx_byte #(
    parameter CLK_HZ = 50_000_000,
    parameter BAUD = 115200
) (
    input clk,
    input rst_n,
    input rx,
    output reg [7:0] data,
    output reg valid
);
    localparam integer BIT_TICKS = CLK_HZ / BAUD;
    reg [2:0] sync_ff;
    reg busy;
    reg [31:0] count;
    reg [3:0] bit_index;
    reg [7:0] shift;

    always @(posedge clk) begin
        if (!rst_n) begin
            sync_ff <= 3'b111;
            busy <= 1'b0;
            count <= 0;
            bit_index <= 0;
            shift <= 0;
            data <= 0;
            valid <= 1'b0;
        end else begin
            sync_ff <= {sync_ff[1:0], rx};
            valid <= 1'b0;
            if (!busy) begin
                if (!sync_ff[2]) begin
                    busy <= 1'b1;
                    count <= BIT_TICKS + BIT_TICKS / 2;
                    bit_index <= 0;
                end
            end else if (count != 0) begin
                count <= count - 1'b1;
            end else begin
                count <= BIT_TICKS - 1;
                if (bit_index < 8) begin
                    shift[bit_index] <= sync_ff[2];
                    bit_index <= bit_index + 1'b1;
                end else begin
                    busy <= 1'b0;
                    data <= shift;
                    valid <= 1'b1;
                end
            end
        end
    end
endmodule

module uart_tx_byte #(
    parameter CLK_HZ = 50_000_000,
    parameter BAUD = 115200
) (
    input clk,
    input rst_n,
    input start,
    input [7:0] data,
    output reg tx,
    output reg busy,
    output reg done
);
    localparam integer BIT_TICKS = CLK_HZ / BAUD;
    reg [31:0] count;
    reg [3:0] bit_index;
    reg [9:0] frame;

    always @(posedge clk) begin
        if (!rst_n) begin
            tx <= 1'b1;
            busy <= 1'b0;
            done <= 1'b0;
            count <= 0;
            bit_index <= 0;
            frame <= 10'h3ff;
        end else begin
            done <= 1'b0;
            if (!busy) begin
                tx <= 1'b1;
                if (start) begin
                    frame <= {1'b1, data, 1'b0};
                    busy <= 1'b1;
                    count <= BIT_TICKS - 1;
                    bit_index <= 0;
                    tx <= 1'b0;
                end
            end else if (count != 0) begin
                count <= count - 1'b1;
            end else begin
                count <= BIT_TICKS - 1;
                bit_index <= bit_index + 1'b1;
                if (bit_index == 9) begin
                    busy <= 1'b0;
                    tx <= 1'b1;
                    done <= 1'b1;
                end else begin
                    tx <= frame[bit_index + 1'b1];
                end
            end
        end
    end
endmodule

module frame_tx #(
    parameter CLK_HZ = 50_000_000,
    parameter BAUD = 115200
) (
    input clk,
    input rst_n,
    input event_valid,
    input [7:0] event_code,
    input [7:0] event_id,
    output tx,
    output busy
);
    reg [7:0] saved_code;
    reg [7:0] saved_id;
    reg [3:0] index;
    reg active;
    reg tx_start;
    reg [7:0] tx_data;
    wire byte_busy;
    wire byte_done;

    uart_tx_byte #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_byte (
        .clk(clk), .rst_n(rst_n), .start(tx_start), .data(tx_data),
        .tx(tx), .busy(byte_busy), .done(byte_done)
    );

    assign busy = active | byte_busy;

    always @(posedge clk) begin
        if (!rst_n) begin
            saved_code <= 0;
            saved_id <= 0;
            index <= 0;
            active <= 1'b0;
            tx_start <= 1'b0;
            tx_data <= 0;
        end else begin
            tx_start <= 1'b0;
            if (!active) begin
                if (event_valid) begin
                    saved_code <= event_code;
                    saved_id <= event_id;
                    index <= 0;
                    active <= 1'b1;
                    tx_data <= 8'haa;
                    tx_start <= 1'b1;
                end
            end else if (byte_done) begin
                if (index == 0) tx_data <= 8'h55;
                else if (index == 1) tx_data <= 8'h10;
                else if (index == 2) tx_data <= 8'd2;
                else if (index == 3) tx_data <= saved_code;
                else if (index == 4) tx_data <= saved_id;
                else if (index == 5) tx_data <= 8'h10 ^ 8'd2 ^ saved_code ^ saved_id;
                else begin
                    active <= 1'b0;
                    index <= 0;
                end
                if (index <= 5) begin
                    index <= index + 1'b1;
                    tx_start <= 1'b1;
                end
            end
        end
    end
endmodule

module seven_seg_status #(
    parameter CLK_HZ = 50_000_000
) (
    input clk,
    input rst_n,
    input [7:0] status0,
    input [7:0] status1,
    input [7:0] status2,
    input [7:0] status3,
    input [1:0] selected_slot,
    input operation_mode,
    output reg [3:0] seg_sel,
    output reg [7:0] seg_led
);
    localparam integer SCAN_TICKS = CLK_HZ / 4000;
    reg [15:0] scan_count;
    reg [1:0] digit;
    reg [25:0] blink_count;
    reg blink;
    reg [7:0] value;

    always @(posedge clk) begin
        if (!rst_n) begin
            scan_count <= 0;
            digit <= 0;
            blink_count <= 0;
            blink <= 1'b0;
        end else begin
            if (scan_count == SCAN_TICKS - 1) begin
                scan_count <= 0;
                digit <= digit + 1'b1;
            end else scan_count <= scan_count + 1'b1;
            if (blink_count == CLK_HZ / 2 - 1) begin
                blink_count <= 0;
                blink <= ~blink;
            end else blink_count <= blink_count + 1'b1;
        end
    end

    always @(*) begin
        case (digit)
            2'd0: begin seg_sel = 4'b0111; value = status0; end
            2'd1: begin seg_sel = 4'b1011; value = status1; end
            2'd2: begin seg_sel = 4'b1101; value = status2; end
            default: begin seg_sel = 4'b1110; value = status3; end
        endcase
        case (value)
            8'd0: seg_led = 8'h3f;
            8'd1: seg_led = 8'h06;
            8'd2: seg_led = 8'h5b;
            8'd3: seg_led = 8'h4f;
            8'd4: seg_led = 8'h66;
            8'd5: seg_led = 8'h6d;
            8'd6: seg_led = 8'h7d;
            default: seg_led = 8'h00;
        endcase
        if (!operation_mode && blink && digit == selected_slot) begin
            seg_led = seg_led | 8'h80;
        end
    end
endmodule
