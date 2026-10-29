library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;
entity audio_fifo_tb is end;
architecture test of audio_fifo_tb is
 signal clk:std_logic:='0';
 signal resetn:std_logic:='0';
 signal data_in,data_out:std_logic_vector(31 downto 0):=(others=>'0');
 signal wr,rd:std_logic_vector(4 downto 0):=(others=>'0');
 signal bclk,lrclk,serial,ra,wa,err:std_logic;
 signal edges:integer:=0;
begin
 clk<=not clk after 5 ns;
 dut:entity work.user_logic generic map(C_NUM_REG=>5,C_SLV_DWIDTH=>32)
 port map(BCLK=>bclk,LRCLK=>lrclk,SDATA_I=>'0',SDATA_O=>serial,
 Bus2IP_Clk=>clk,Bus2IP_Resetn=>resetn,Bus2IP_Data=>data_in,Bus2IP_BE=>"1111",
 Bus2IP_RdCE=>rd,Bus2IP_WrCE=>wr,IP2Bus_Data=>data_out,
 IP2Bus_RdAck=>ra,IP2Bus_WrAck=>wa,IP2Bus_Error=>err);
 process(lrclk) begin if falling_edge(lrclk) then edges<=edges+1;end if;end process;
 process
 procedure write_reg(sel:std_logic_vector(4 downto 0);value:std_logic_vector(31 downto 0)) is
 begin wait until falling_edge(clk);wr<=sel;data_in<=value;wait until falling_edge(clk);wr<="00000";end;
 variable before:integer;
 begin
 wait for 100 ns;resetn<='1';wait for 20 ns;
 rd<="00010";wait for 20 ns;assert data_out=x"53414631" report "signature" severity failure;
 write_reg("00001",x"A5000001");write_reg("00010",x"00000060");
 for i in 1 to 96 loop write_reg("00100",std_logic_vector(to_unsigned(i,32)));end loop;
 rd<="00100";wait for 20 ns;assert unsigned(data_out)=96 report "prefill" severity failure;
 before:=edges;write_reg("00001",x"A5000002");wait for 2 ms;
 assert edges-before=96 report "48kHz clock" severity failure;
 rd<="10000";wait for 20 ns;assert unsigned(data_out)=96 report "playback count" severity failure;
 rd<="01000";wait for 20 ns;assert unsigned(data_out)=0 report "unexpected underrun" severity failure;
 write_reg("00001",x"A5000001");write_reg("00010",x"00000008");
 write_reg("00100",x"00001234");write_reg("00100",x"00001234");
 write_reg("00001",x"A5000002");wait for 200 us;
 rd<="10000";wait for 20 ns;assert unsigned(data_out)=8 report "clock must not stretch" severity failure;
 rd<="01000";wait for 20 ns;assert unsigned(data_out)=6 report "underrun count" severity failure;
 write_reg("00001",x"A5000001");
 for i in 1 to 8300 loop write_reg("00100",x"00001234");end loop;
 rd<="00100";wait for 20 ns;assert unsigned(data_out)=8192 report "FIFO full protection" severity failure;
 report "PASS: exact 48kHz, prefill, playback count, underrun clock, overflow guard" severity note;
 std.env.finish;
 wait;
 end process;
end;
